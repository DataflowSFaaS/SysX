import sys
import time
import multiprocessing
from multiprocessing import Pool

import pandas as pd
from timeit import default_timer as timer

from system_x.client.sync_client import SyncSysXClient
from system_x.common.local_state_backends import LocalStateBackend
from system_x.common.operator import Operator
from system_x.common.stateflow_graph import StateflowGraph
from system_x.common.stateful_function import make_key_hashable

import kafka_output_consumer
import calculate_metrics

from tqdm import tqdm

from ycsb import ycsb_operator
from zipfian_generator import ZipfGenerator

# A run with sensible arguments: python client.py 1 10 4 0 100 10 results 0 10

threads = int(sys.argv[1])
N_ENTITIES = int(sys.argv[2])
N_PARTITIONS = int(sys.argv[3])
STARTING_MONEY = 1_000_000
ZIPF_CONST = float(sys.argv[4])
messages_per_second = int(sys.argv[5])
sleeps_per_second = 100
sleep_time = 0.0085
seconds = int(sys.argv[6])
key_list: list[int] = list(range(N_ENTITIES))
SYSX_HOST: str = 'localhost'
SYSX_PORT: int = 8886
# SYSX_HOST: str = '35.229.80.128'
# SYSX_PORT: int = 8888
KAFKA_URL = 'localhost:9092'
# KAFKA_URL = '35.229.114.18:9094'
SAVE_DIR: str = sys.argv[7]
warmup_seconds: int = int(sys.argv[8])
run_with_validation = bool(sys.argv[9])
####################################################################################################################
g = StateflowGraph('ycsb-benchmark', operator_state_backend=LocalStateBackend.DICT)
ycsb_operator.set_n_partitions(N_PARTITIONS)
g.add_operators(ycsb_operator)

def submit_graph(system_x: SyncSysXClient):
    print(f'Partitions: {list(g.nodes.values())[0].n_partitions}')
    system_x.submit_dataflow(g)
    print("Graph submitted")


def ycsb_init(system_x: SyncSysXClient, operator: Operator, keys: list[int]):
    submit_graph(system_x)
    time.sleep(5)
    # INSERT
    partitions: dict[int, dict] = {p: {} for p in range(N_PARTITIONS)}
    for i in tqdm(keys):
        partition: int = make_key_hashable(i) % operator.n_partitions
        partitions[partition] |= {i: STARTING_MONEY}
        if i % 100_000 == 0 or i == len(keys) - 1:
            for partition, kv_pairs in partitions.items():
                system_x.send_batch_insert(operator=operator,
                                       partition=partition,
                                       function='insert_batch',
                                       key_value_pairs=kv_pairs)
            partitions: dict[int, dict] = {p: {} for p in range(N_PARTITIONS)}


def transactional_ycsb_generator(keys, operator: Operator,
                                 n: int, zipf_const: float) -> [Operator, int, str, tuple[int, ]]:
    zipf_gen = ZipfGenerator(items=n, zipf_const=zipf_const)
    uniform_gen = ZipfGenerator(items=n, zipf_const=0.0)
    while True:
        key = keys[next(uniform_gen)]
        key2 = keys[next(zipf_gen)]
        while (key2 == key or
               make_key_hashable(key2) % N_PARTITIONS == make_key_hashable(key) % N_PARTITIONS):
            key2 = keys[next(zipf_gen)]
        yield operator, key, 'transfer', (key2, )


def read_only_ycsb_generator(keys, operator: Operator, n: int, zipf_const: float) -> [Operator, int, str, tuple[int, ]]:
    zipf_gen = ZipfGenerator(items=n, zipf_const=zipf_const)
    while True:
        key = keys[next(zipf_gen)]
        yield operator, key, 'read', ()


def benchmark_runner(proc_num) -> dict[bytes, dict]:
    print(f'Generator: {proc_num} starting')
    system_x = SyncSysXClient(SYSX_HOST, SYSX_PORT, kafka_url=KAFKA_URL, start_futures_consumer=False)
    system_x.open()
    ycsb_generator = transactional_ycsb_generator(key_list, ycsb_operator, N_ENTITIES, zipf_const=ZIPF_CONST)
    timestamp_futures: dict[bytes, dict] = {}
    start = timer()
    for _ in range(seconds):
        sec_start = timer()
        for i in range(messages_per_second):
            if i % (messages_per_second // sleeps_per_second) == 0:
                time.sleep(sleep_time)
            operator, key, func_name, params = next(ycsb_generator)
            future = system_x.send_event(operator=operator,
                                     key=key,
                                     function=func_name,
                                     params=params)
            timestamp_futures[future.request_id] = {"op": f'{func_name} {key}->{params[0]}'}
        system_x.flush()
        sec_end = timer()
        lps = sec_end - sec_start
        if lps < 1:
            time.sleep(1 - lps)
        sec_end2 = timer()
        print(f'Latency per second: {sec_end2 - sec_start}')
    end = timer()
    print(f'Average latency per second: {(end - start) / seconds}')

    system_x.close()

    for key, metadata in system_x.delivery_timestamps.items():
        timestamp_futures[key]["timestamp"] = metadata
    return timestamp_futures


def main():
    print('Generate and push workload to SysX')

    if N_ENTITIES < 3:
        print("Impossible to run this benchmark with one key")
        return

    system_x_client = SyncSysXClient(SYSX_HOST, SYSX_PORT, kafka_url=KAFKA_URL, start_futures_consumer=False)

    system_x_client.open()

    ycsb_init(system_x_client, ycsb_operator, key_list)

    system_x_client.close()

    time.sleep(5)

    with Pool(threads) as p:
        results = p.map(benchmark_runner, range(threads))

    results = {k: v for d in results for k, v in d.items()}
    assert len(results) == messages_per_second * seconds * threads

    if run_with_validation:
        # wait for system to stabilize
        time.sleep(60)

        system_x_client = SyncSysXClient(SYSX_HOST, SYSX_PORT, kafka_url=KAFKA_URL, start_futures_consumer=False)

        system_x_client.open()

        print('Starting Consistency measurement')

        validation_results = {}

        for key in key_list:
            future = system_x_client.send_event(operator=ycsb_operator,
                                            key=key,
                                            function="read")
            validation_results[future.request_id] = {"op": f'read -> {key}'}

        system_x_client.close()

        for request_id, metadata in system_x_client.delivery_timestamps.items():
            validation_results[request_id]["timestamp"] = metadata

        assert len(validation_results) == N_ENTITIES

    pd.DataFrame({"request_id": list(results.keys()),
                  "timestamp": [res["timestamp"] for res in results.values()],
                  "op": [res["op"] for res in results.values()]
                  }).sort_values("timestamp").to_csv(f'{SAVE_DIR}/client_requests.csv', index=False)

    print('Workload completed')


if __name__ == "__main__":
    multiprocessing.set_start_method('fork')
    main()

    print()
    kafka_output_consumer.main(SAVE_DIR)

    print()
    calculate_metrics.main(
        N_ENTITIES,
        N_PARTITIONS,
        messages_per_second,
        ZIPF_CONST,
        threads,
        warmup_seconds,
        SAVE_DIR,
        run_with_validation
    )

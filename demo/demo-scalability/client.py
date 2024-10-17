import random
import sys
import time
from collections import defaultdict
from multiprocessing import Pool

import pandas as pd
from timeit import default_timer as timer

from system_x.client.sync_client import SyncSysXClient
from system_x.common.local_state_backends import LocalStateBackend
from system_x.common.operator import Operator
from system_x.common.stateflow_graph import StateflowGraph
from system_x.common.stateful_function import make_key_hashable

from tqdm import tqdm

from ycsb import ycsb_operator


threads = int(sys.argv[1])
PERC_MULT = float(sys.argv[2])
N_PARTITIONS = int(sys.argv[3])
N_ENTITIES = 1_000_000 * N_PARTITIONS
STARTING_MONEY = 1_000_000
messages_per_second = int(sys.argv[4])
sleeps_per_second = 100
sleep_time = 0.0085
seconds = int(sys.argv[5])
key_list: list[int] = list(range(N_ENTITIES))
SYSX_HOST: str = 'localhost'
SYSX_PORT: int = 8886
KAFKA_URL = 'localhost:9092'
SAVE_DIR: str = sys.argv[6]

g = StateflowGraph('ycsb-benchmark', operator_state_backend=LocalStateBackend.DICT)
####################################################################################################################
ycsb_operator.set_n_partitions(N_PARTITIONS)
g.add_operators(ycsb_operator)

def submit_graph(system_x: SyncSysXClient):
    print(list(g.nodes.values())[0].n_partitions)
    system_x.submit_dataflow(g)
    print("Graph submitted")


def ycsb_init(system_x: SyncSysXClient, operator: Operator):
    submit_graph(system_x)
    time.sleep(5)
    # INSERT
    partitions: dict[int, dict] = {p: {} for p in range(N_PARTITIONS)}
    for i in tqdm(range(N_ENTITIES)):
        partition: int = make_key_hashable(i) % operator.n_partitions
        partitions[partition] |= {i: STARTING_MONEY}
        if i % 100_000 == 0 or i == N_ENTITIES - 1:
            for partition, kv_pairs in partitions.items():
                system_x.send_batch_insert(operator=operator,
                                       partition=partition,
                                       function='insert_batch',
                                       key_value_pairs=kv_pairs)
            partitions: dict[int, dict] = {p: {} for p in range(N_PARTITIONS)}


def transactional_ycsb_generator(operator: Operator) -> [Operator, int, str, tuple[int, ]]:
    # partition: list of keys
    key_per_partition: dict[int, list[int]] = defaultdict(list)
    for i in range(N_ENTITIES):
        part = i % N_PARTITIONS
        key_per_partition[part].append(i)
    while True:
        part_1 = random.randint(0, N_PARTITIONS - 1)
        if PERC_MULT > 0.0:
            coin = random.random()
            if coin > PERC_MULT:
                part_2 = part_1
            else:
                part_2 = random.choice(list(set([x for x in range(N_PARTITIONS)]) - {part_1}))
        else:
            part_2 = part_1
        key1 = random.choice(key_per_partition[part_1])
        key2 = random.choice(key_per_partition[part_2])
        while key2 == key1:
            key2 = random.choice(key_per_partition[part_2])
        yield operator, key1, 'transfer', (key2, )


def benchmark_runner(proc_num) -> dict[bytes, dict]:
    print(f'Generator: {proc_num} starting')
    system_x = SyncSysXClient(SYSX_HOST, SYSX_PORT, kafka_url=KAFKA_URL)
    system_x.open()
    ycsb_generator = transactional_ycsb_generator(ycsb_operator)
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
    if N_ENTITIES < 3:
        print("Impossible to run this benchmark with one key")
        return

    system_x_client = SyncSysXClient(SYSX_HOST, SYSX_PORT, kafka_url=KAFKA_URL)

    system_x_client.open()

    ycsb_init(system_x_client, ycsb_operator)

    system_x_client.close()

    time.sleep(5)

    with Pool(threads) as p:
        results = p.map(benchmark_runner, range(threads))

    results = {k: v for d in results for k, v in d.items()}
    assert len(results) == messages_per_second * seconds * threads

    pd.DataFrame({"request_id": list(results.keys()),
                  "timestamp": [res["timestamp"] for res in results.values()],
                  "op": [res["op"] for res in results.values()]
                  }).sort_values("timestamp").to_csv(f'{SAVE_DIR}/client_requests.csv', index=False)


if __name__ == "__main__":
    main()

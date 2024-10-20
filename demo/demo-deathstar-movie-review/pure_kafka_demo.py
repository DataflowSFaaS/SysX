import hashlib
import random
import uuid
from movie_data import movie_data
import sys

from timeit import default_timer as timer
import time
from multiprocessing import Pool

import pandas as pd

from system_x.common.local_state_backends import LocalStateBackend
from system_x.common.stateflow_graph import StateflowGraph
from system_x.client import SyncSysXClient

from graph import (user_operator, movie_info_operator, plot_operator, movie_id_operator, compose_review_operator,
                   rating_operator, text_operator, unique_id_operator, frontend_operator)

from workload_data import movie_titles, charset

SAVE_DIR: str = sys.argv[1]
threads = int(sys.argv[2])
N_PARTITIONS = int(sys.argv[3])
messages_per_second = int(sys.argv[4])
sleeps_per_second = 100
sleep_time = 0.0085
seconds = int(sys.argv[5])
SYSX_HOST: str = 'localhost'
SYSX_PORT: int = 8886
KAFKA_URL = 'localhost:9092'

g = StateflowGraph('deathstar_movie_review', operator_state_backend=LocalStateBackend.DICT)
####################################################################################################################
compose_review_operator.set_n_partitions(N_PARTITIONS)
movie_id_operator.set_n_partitions(N_PARTITIONS)
movie_info_operator.set_n_partitions(N_PARTITIONS)
plot_operator.set_n_partitions(N_PARTITIONS)
rating_operator.set_n_partitions(N_PARTITIONS)
text_operator.set_n_partitions(N_PARTITIONS)
unique_id_operator.set_n_partitions(N_PARTITIONS)
user_operator.set_n_partitions(N_PARTITIONS)
frontend_operator.set_n_partitions(N_PARTITIONS)
g.add_operators(compose_review_operator,
                movie_id_operator,
                movie_info_operator,
                plot_operator,
                rating_operator,
                text_operator,
                unique_id_operator,
                user_operator,
                frontend_operator)


def populate_user(system_x_client: SyncSysXClient):
    for i in range(1000):
        user_id = f'user{i}'
        username = f'username_{i}'
        password = f'password_{i}'
        hasher = hashlib.new('sha512')
        salt = uuid.uuid1().bytes
        hasher.update(password.encode())
        hasher.update(salt)

        password_hash = hasher.hexdigest()

        user_data = {
            "userId": user_id,
            "FirstName": "firstname",
            "LastName": "lastname",
            "Username": username,
            "Password": password_hash,
            "Salt": salt
        }
        system_x_client.send_event(operator=user_operator,
                               key=username,
                               function='register_user',
                               params=(user_data,))


def populate_movie(system_x_client: SyncSysXClient):
    for movie in movie_data:
        movie_id = movie["MovieId"]
        system_x_client.send_event(operator=movie_info_operator,
                               key=movie_id,
                               function='write',
                               params=(movie,))

        system_x_client.send_event(operator=plot_operator,
                               key=movie_id,
                               function='write',
                               params=("plot",))

        system_x_client.send_event(operator=movie_id_operator,
                               key=movie["Title"],
                               function='register_movie_id',
                               params=(movie_id,))


def submit_graph(system_x: SyncSysXClient):
    print(list(g.nodes.values())[0].n_partitions)
    system_x.submit_dataflow(g)
    print("Graph submitted")


def deathstar_init(system_x: SyncSysXClient):
    submit_graph(system_x)
    time.sleep(60)
    populate_user(system_x)
    populate_movie(system_x)
    system_x.flush()
    print('Data populated')
    time.sleep(2)


def compose_review(c):
    user_index = random.randint(0, 999)
    username = f"username_{user_index}"
    password = f"password_{user_index}"
    title = random.choice(movie_titles)
    rating = random.randint(0, 10)
    text = ''.join(random.choice(charset) for _ in range(256))
    return frontend_operator, c, "compose", (username, title, rating, text)


def deathstar_workload_generator():
    c = 0
    while True:
        yield compose_review(c)
        c += 1


def benchmark_runner(proc_num) -> dict[bytes, dict]:
    print(f'Generator: {proc_num} starting')
    system_x = SyncSysXClient(SYSX_HOST, SYSX_PORT, kafka_url=KAFKA_URL)
    system_x.open()
    deathstar_generator = deathstar_workload_generator()
    timestamp_futures: dict[bytes, dict] = {}
    start = timer()
    for _ in range(seconds):
        sec_start = timer()
        for i in range(messages_per_second):
            if i % (messages_per_second // sleeps_per_second) == 0:
                time.sleep(sleep_time)
            operator, key, func_name, params = next(deathstar_generator)
            future = system_x.send_event(operator=operator,
                                     key=key,
                                     function=func_name,
                                     params=params)
            timestamp_futures[future.request_id] = {"op": f'{func_name} {key}->{params}'}
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
    system_x_client = SyncSysXClient(SYSX_HOST, SYSX_PORT, kafka_url=KAFKA_URL)

    system_x_client.open()

    deathstar_init(system_x_client)

    system_x_client.flush()

    time.sleep(1)

    with Pool(threads) as p:
        results = p.map(benchmark_runner, range(threads))

    system_x_client.close()

    results = {k: v for d in results for k, v in d.items()}

    pd.DataFrame({"request_id": list(results.keys()),
                  "timestamp": [res["timestamp"] for res in results.values()],
                  "op": [res["op"] for res in results.values()]
                  }).sort_values("timestamp").to_csv(f'{SAVE_DIR}/client_requests.csv', index=False)


if __name__ == "__main__":
    main()

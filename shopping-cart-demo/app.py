import os
import random
import uuid

from timeit import default_timer as timer

from sanic import Sanic, json, text
from system_x.client.system_x_future import SysXResponse
from system_x.common.local_state_backends import LocalStateBackend
from system_x.common.stateflow_graph import StateflowGraph

from system_x.client import AsyncSysXClient
from system_x.common.stateful_function import make_key_hashable

from functions.order import order_operator
from functions.payment import payment_operator
from functions.stock import stock_operator

app = Sanic("wdm-project")

SYSX_HOST: str = os.environ['SYSX_HOST']
SYSX_PORT: int = int(os.environ['SYSX_PORT'])
KAFKA_URL: str = os.environ['KAFKA_URL']

system_x_client = AsyncSysXClient(SYSX_HOST, SYSX_PORT, KAFKA_URL)

app.add_task(system_x_client.open())


@app.post('/hello')
async def hello(_):
    return text('Hey', status=200)


@app.post('/submit/<n_partitions>')
async def submit_dataflow_graph(_, n_partitions: int):
    n_partitions: int = int(n_partitions)
    g = StateflowGraph('wdm-project', operator_state_backend=LocalStateBackend.DICT)

    order_operator.set_n_partitions(n_partitions)
    stock_operator.set_n_partitions(n_partitions)
    payment_operator.set_n_partitions(n_partitions)

    g.add_operators(order_operator, stock_operator, payment_operator)
    await system_x_client.submit_dataflow(g)
    return json({'Graph submitted': True})


@app.post('/payment/create_user')
async def create_user(_):
    start = timer()
    user_key: str = str(uuid.uuid4())
    future = await system_x_client.send_event(operator=payment_operator,
                                              key=user_key,
                                              function="create_user")
    result: SysXResponse = await future.get()
    end = timer()
    c_lat = round((end - start) * 1000, 0)
    return json({'user_id': result.response,
                 'system_x_latency_ms': result.system_x_latency_ms,
                 'client_latency_ms': c_lat,
                 'client_added_latency': c_lat - result.system_x_latency_ms,
                 'in_t': result.in_timestamp,
                 'out_t': result.out_timestamp})


@app.post('/payment/batch_init/<n>/<starting_money>')
async def batch_init_users(_, n: int, starting_money: int):
    n = int(n)
    starting_money = int(starting_money)
    partitions: dict[int, dict] = {p: {} for p in range(payment_operator.n_partitions)}
    for i in range(n):
        partition: int = make_key_hashable(i) % payment_operator.n_partitions
        partitions[partition] |= {i: {"credit": starting_money}}
        if i % 10_000 == 0 or i == n - 1:
            for partition, kv_pairs in partitions.items():
                await system_x_client.send_batch_insert(operator=payment_operator,
                                                        partition=partition,
                                                        function='batch_create',
                                                        key_value_pairs=kv_pairs)
    return json(partitions)


@app.post('/payment/add_funds/<user_key>/<amount>')
async def add_credit(_, user_key: str, amount: int):
    future = await system_x_client.send_event(operator=payment_operator,
                                              key=user_key,
                                              function="add_credit",
                                              params=(int(amount),))
    result: SysXResponse = await future.get()
    return text(f"User: {user_key} credit updated to: {result.response}", status=200)


@app.get('/payment/find_user/<user_key>')
async def find_user(_, user_key: str):
    future = await system_x_client.send_event(operator=payment_operator,
                                              key=user_key,
                                              function="find")
    result: SysXResponse = await future.get()
    return json(result.response)


@app.post('/stock/item/create/<price>')
async def create_item(_, price: int):
    item_key: str = str(uuid.uuid4())
    future = await system_x_client.send_event(operator=stock_operator,
                                              key=item_key,
                                              function="create_item",
                                              params=(int(price),))
    result: SysXResponse = await future.get()
    return json({'item_id': result.response})


@app.post('/stock/batch_init/<n>/<starting_stock>/<item_price>')
async def batch_init_items(_, n: int, starting_stock: int, item_price: int):
    n = int(n)
    starting_stock = int(starting_stock)
    item_price = int(item_price)
    partitions: dict[int, dict] = {p: {} for p in range(stock_operator.n_partitions)}
    for i in range(n):
        partition: int = make_key_hashable(i) % stock_operator.n_partitions
        partitions[partition] |= {i: {"stock": starting_stock,
                                      "price": item_price
                                      }
                                  }
        if i % 10_000 == 0 or i == n - 1:
            for partition, kv_pairs in partitions.items():
                await system_x_client.send_batch_insert(operator=stock_operator,
                                                        partition=partition,
                                                        function='batch_create',
                                                        key_value_pairs=kv_pairs)
    return json(partitions)


@app.post('/stock/add/<item_key>/<amount>')
async def add_stock(_, item_key: str, amount: int):
    future = await system_x_client.send_event(operator=stock_operator,
                                              key=item_key,
                                              function="add_stock",
                                              params=(int(amount),))
    result: SysXResponse = await future.get()
    return text(f"Item: {item_key} stock updated to: {result.response}", status=200)


@app.get('/stock/find/<item_key>')
async def find_item(_, item_key: str):
    future = await system_x_client.send_event(operator=stock_operator,
                                              key=item_key,
                                              function="find")
    result: SysXResponse = await future.get()
    return json(result.response)


@app.post('/orders/create/<user_key>')
async def create_order(_, user_key: str):
    order_key: str = str(uuid.uuid4())
    future = await system_x_client.send_event(operator=order_operator,
                                              key=order_key,
                                              function="create_order",
                                              params=(user_key,))
    result: SysXResponse = await future.get()
    return json({'order_id': result.response})


@app.post('/orders/batch_init/<n>/<n_items>/<n_users>/<item_price>')
async def batch_init_orders(_, n: int, n_items: int, n_users: int, item_price: int):
    n = int(n)
    n_items = int(n_items)
    n_users = int(n_users)
    item_price = int(item_price)
    partitions: dict[int, dict] = {p: {} for p in range(order_operator.n_partitions)}
    for i in range(n):
        partition: int = make_key_hashable(i) % order_operator.n_partitions
        user_id = random.randint(0, n_users - 1)
        item1_id = random.randint(0, n_items - 1)
        item2_id = random.randint(0, n_items - 1)
        while item1_id == item2_id:
            item2_id = random.randint(0, n_items - 1)
        partitions[partition] |= {i: {"paid": False,
                                      "items": {item1_id: 1, item2_id: 1},
                                      "user_id": user_id,
                                      "total_cost": 2 * item_price
                                      }
                                  }
        if i % 1_000 == 0 or i == n - 1:
            for partition, kv_pairs in partitions.items():
                await system_x_client.send_batch_insert(operator=order_operator,
                                                        partition=partition,
                                                        function='batch_create',
                                                        key_value_pairs=kv_pairs)
    return json(partitions)


@app.get('/orders/find/<order_key>')
async def find_order(_, order_key: str):
    future = await system_x_client.send_event(operator=order_operator,
                                              key=order_key,
                                              function="find")
    result: SysXResponse = await future.get()
    return json(result.response)


@app.post('/orders/addItem/<order_key>/<item_key>/<quantity>')
async def add_item(_, order_key: str, item_key: str, quantity: int):
    future = await system_x_client.send_event(operator=order_operator,
                                              key=order_key,
                                              function="add_item",
                                              params=(item_key, int(quantity)))
    result: SysXResponse = await future.get()
    return text(f"Item: {item_key} added to: {order_key} price updated to: {result.response}",
                status=200)


@app.post('/orders/checkout/<order_key>')
async def checkout_order(_, order_key: str):
    # start = timer()
    future = await system_x_client.send_event(operator=order_operator,
                                              key=order_key,
                                              function="checkout")
    result: SysXResponse = await future.get()
    # end = timer()
    # print(f"Result: {result.response} |"
    #       f" Checkout API latency: {round((end - start) * 1000, 0)} ms |"
    #       f" SysX latency: {result.system_x_latency_ms}")
    if ((result.response.startswith("User") and result.response.endswith("does not have enough credit")) or
            (result.response.startswith("Item") and result.response.endswith("does not have enough stock"))):
        return text(result.response, status=400)
    return text(f'Checkout started result: {result.response}', status=200)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=False)

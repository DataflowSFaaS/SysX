from system_x.common.operator import Operator
from system_x.common.stateful_function import StatefulFunction


new_order_operator = Operator('new_order')


@new_order_operator.register
async def insert(ctx: StatefulFunction, new_order_data: dict):
    ctx.put(new_order_data)


@new_order_operator.register
async def insert_batch(ctx: StatefulFunction, key_value_pairs: dict[any, any]):
    ctx.batch_insert(key_value_pairs)

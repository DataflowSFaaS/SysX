from system_x.common.operator import Operator
from system_x.common.stateful_function import StatefulFunction


customer_operator = Operator('customer')


class InvalidItemId(Exception):
    pass


class CustomerDoesNotExist(Exception):
    pass


@customer_operator.register
async def insert(ctx: StatefulFunction, customer: dict):
    ctx.put(customer)


@customer_operator.register
async def insert_batch(ctx: StatefulFunction, key_value_pairs: dict[any, any]):
    ctx.batch_insert(key_value_pairs)


@customer_operator.register
async def get_customer(ctx: StatefulFunction, frontend_key):
    customer_data = ctx.get()
    if customer_data is None:
        raise CustomerDoesNotExist(f'Customer with id: {ctx.key} does not exist in the customer operator')
    ctx.call_remote_async(
        'new_order_txn',
        'get_customer',
        frontend_key,
        (customer_data, )
    )


@customer_operator.register
async def pay(ctx: StatefulFunction, frontend_key, h_amount, d_id, w_id):
    customer_data = ctx.get()
    if customer_data is None:
        raise CustomerDoesNotExist(f'Customer with id: {ctx.key} does not exist in the customer operator')

    customer_data['C_BALANCE'] = float(customer_data['C_BALANCE']) - h_amount
    customer_data['C_YTD_PAYMENT'] = float(customer_data['C_YTD_PAYMENT']) + h_amount
    customer_data['C_PAYMENT_CNT'] = float(customer_data['C_PAYMENT_CNT']) + 1

    if customer_data['C_CREDIT'] == "BC":
        # ----------------------------------
        # Update Bad Credit Customer Query
        # ----------------------------------
        new_data = " ".join(map(str, [ctx.key, customer_data['C_D_ID'], customer_data['C_W_ID'], d_id, w_id, h_amount]))
        customer_data['C_DATA'] = (new_data + "|" + customer_data['C_DATA'])

        if len(customer_data['C_DATA']) > 500:
            customer_data['C_DATA'] = customer_data['C_DATA'][:500]
    else:
        # -----------------------------------
        # Update Good Credit Customer Query
        # -----------------------------------
        customer_data['C_DATA'] = ''
    ctx.put(customer_data)
    ctx.call_remote_async(
        'payment_txn',
        'get_customer',
        frontend_key,
        (customer_data, )
    )

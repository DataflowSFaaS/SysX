from system_x.common.operator import Operator
from system_x.common.stateful_function import StatefulFunction

movie_info_operator = Operator('movie_info')
# key: movie_id


@movie_info_operator.register
async def write(ctx: StatefulFunction, info: dict):
    ctx.put(info)
    return ctx.key

from abc import ABC, abstractmethod

from system_x.common.stateflow_graph import StateflowGraph
from system_x.common.stateflow_worker import StateflowWorker


class BaseScheduler(ABC):

    @staticmethod
    @abstractmethod
    async def schedule(workers: list[StateflowWorker],
                       execution_graph: StateflowGraph,
                       network_manager):
        raise NotImplementedError

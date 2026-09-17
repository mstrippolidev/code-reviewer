"""
    Factory for creating consumers.
"""
from api.indexing.consumers.dlq_consumer import RepoIndexDlqConsumer
from api.indexing.consumers.dlq_notifier import DlqNotifier
from api.indexing.consumers.interface import ConsumerInterface
from api.indexing.consumers.repo_index_consumer import RepoIndexConsumer, RepoIndexConsumerDependencies

class FactoryError(Exception):
    """
        Raise when key does not exists
    """

class FactoryConsumer:
    """
        Factory for creating consumers.
    """
    @staticmethod
    def create_consumer(
        key: str, dependencies: RepoIndexConsumerDependencies | DlqNotifier
    ) -> ConsumerInterface:
        if key == 'repo_indexing':
            return RepoIndexConsumer(dependencies)
        if key == 'repo_indexing_dlq':
            return RepoIndexDlqConsumer(dependencies)
        raise FactoryError(f"{key} does not exists")
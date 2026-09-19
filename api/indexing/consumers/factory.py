"""
    Factory for creating consumers.
"""
from api.indexing.consumers.dlq_consumer import RepoIndexDlqConsumer
from api.indexing.consumers.dlq_notifier import DlqNotifier
from api.indexing.consumers.interface import ConsumerInterface
from api.indexing.consumers.repo_file_index_consumer import RepoFileIndexConsumer, RepoFileIndexConsumerDependencies
from api.indexing.consumers.repo_index_consumer import RepoIndexConsumer, RepoIndexConsumerDependencies

ConsumerDependencies = RepoIndexConsumerDependencies | RepoFileIndexConsumerDependencies | DlqNotifier

class FactoryError(Exception):
    """
        Raise when key does not exists
    """

class FactoryConsumer:
    """
        Factory for creating consumers.
    """
    @staticmethod
    def create_consumer(key: str, dependencies: ConsumerDependencies) -> ConsumerInterface:
        if key == 'repo_indexing':
            return RepoIndexConsumer(dependencies)
        if key == 'repo_indexing_dlq':
            return RepoIndexDlqConsumer(dependencies)
        if key == 'repo_file_indexing':
            return RepoFileIndexConsumer(dependencies)
        raise FactoryError(f"{key} does not exists")
from backend.app.services.task_queue import TaskQueue


class FakeRepository:
    def __init__(self):
        self.claimed_lanes = []

    def claim_next(self, lane):
        self.claimed_lanes.append(lane)
        return {"id": "instagram-task-1", "platform": lane}

    def claim_batch(self, *_args, **_kwargs):
        raise AssertionError("Instagram worker must not claim a batch")


class FakeDispatcher:
    def __init__(self):
        self.tasks = []

    def dispatch(self, task):
        self.tasks.append(task)
        return task

    def dispatch_batch(self, _tasks):
        raise AssertionError("Instagram worker must not dispatch a batch")


def test_instagram_worker_claims_and_dispatches_one_task():
    repository = FakeRepository()
    dispatcher = FakeDispatcher()
    queue = TaskQueue(repository=repository, dispatcher=dispatcher)

    result = queue.run_once("instagram")

    assert result["id"] == "instagram-task-1"
    assert repository.claimed_lanes == ["instagram"]
    assert [task["id"] for task in dispatcher.tasks] == ["instagram-task-1"]

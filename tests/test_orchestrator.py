from remote_browser_tool.browser.base import BrowserSession, BrowserState
from remote_browser_tool.config import RunnerConfig
from remote_browser_tool.llm.mock import ScriptedLLM
from remote_browser_tool.memory.base import InMemoryStore
from remote_browser_tool.models import (
    BrowserAction,
    BrowserActionType,
    DirectiveStatus,
    LLMDirective,
    NotificationEvent,
    NotificationLevel,
    UserInterventionRequest,
)
from remote_browser_tool.notifications.base import Notifier
from remote_browser_tool.orchestrator.control import ManualPauseController
from remote_browser_tool.orchestrator.runner import Orchestrator
from remote_browser_tool.user_portal.base import UserInteractionPortal


class StubBrowserSession(BrowserSession):
    def __init__(self) -> None:
        self.actions: list[BrowserAction] = []
        self.state = BrowserState(url="https://start", title="Start", last_action=None)
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def execute(self, action: BrowserAction) -> BrowserState:
        self.actions.append(action)
        self.state = BrowserState(
            url=action.url or self.state.url,
            title=self.state.title,
            last_action=action.type.value,
        )
        return self.state

    def snapshot(self) -> BrowserState:
        return self.state

    def screenshot(self) -> bytes:
        return b"stub-screenshot"


class CollectingNotifier(Notifier):
    def __init__(self) -> None:
        self.events: list[NotificationEvent] = []

    def notify(self, event: NotificationEvent) -> None:
        self.events.append(event)


class StubPortal(UserInteractionPortal):
    def __init__(self, finish: bool) -> None:
        self.finish = finish
        self.started = False
        self.request: UserInterventionRequest | None = None
        self.info = None

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def update_connection_info(self, info) -> None:
        self.info = info

    def request_intervention(self, request: UserInterventionRequest) -> NotificationEvent:
        self.request = request
        return NotificationEvent(
            type="user_action_required",
            message=request.reason,
            level=NotificationLevel.WARNING,
            data={"instructions": request.instructions},
        )

    def wait_until_finished(self, timeout: float | None = None) -> bool:
        return self.finish


def build_config() -> RunnerConfig:
    return RunnerConfig.model_validate(
        {
            "task": {"description": "Test task"},
            "browser": {"enable_vnc": False, "headless": True},
            "llm": {"provider": "mock", "model": "mock"},
            "notifications": {"channel": "console"},
            "portal": {"host": "127.0.0.1", "port": 9000},
        }
    )


def test_orchestrator_successful_flow():
    directives = [
        LLMDirective(
            status=DirectiveStatus.CONTINUE,
            message="Navigating",
            actions=[
                BrowserAction(
                    type=BrowserActionType.NAVIGATE,
                    url="https://example.com",
                )
            ],
            memory_to_write=["Visited example"],
        ),
        LLMDirective(
            status=DirectiveStatus.WAIT_FOR_USER,
            user_request=UserInterventionRequest(
                reason="captcha",
                instructions="solve the captcha",
            ),
        ),
        LLMDirective(status=DirectiveStatus.FINISHED, message="Done"),
    ]
    llm = ScriptedLLM(directives)
    browser = StubBrowserSession()
    memory = InMemoryStore(max_entries=10)
    notifier = CollectingNotifier()
    portal = StubPortal(finish=True)

    orchestrator = Orchestrator(
        config=build_config(),
        llm=llm,
        browser=browser,
        memory=memory,
        notifier=notifier,
        user_portal=portal,
    )
    success = orchestrator.run()
    assert success is True
    assert browser.actions[0].url == "https://example.com"
    assert memory.get()[0].content == "Visited example"
    assert portal.request is not None
    event_types = [event.type for event in notifier.events]
    assert "task_started" in event_types
    assert "task_finished" in event_types


def test_orchestrator_manual_step_timeout():
    directives = [
        LLMDirective(
            status=DirectiveStatus.WAIT_FOR_USER,
            user_request=UserInterventionRequest(
                reason="check",
                instructions="do it",
            ),
        )
    ]
    llm = ScriptedLLM(directives)
    browser = StubBrowserSession()
    memory = InMemoryStore(max_entries=10)
    notifier = CollectingNotifier()
    portal = StubPortal(finish=False)

    orchestrator = Orchestrator(
        config=build_config(),
        llm=llm,
        browser=browser,
        memory=memory,
        notifier=notifier,
        user_portal=portal,
    )
    success = orchestrator.run()
    assert success is False
    event_types = [event.type for event in notifier.events]
    assert "task_failed" not in event_types  # failure due to timeout triggers orchestrator_error
    assert "orchestrator_error" in event_types


def test_orchestrator_manual_pause_flow():
    directives = [
        LLMDirective(status=DirectiveStatus.CONTINUE),
        LLMDirective(status=DirectiveStatus.FINISHED, message="Done"),
    ]
    llm = ScriptedLLM(directives)
    browser = StubBrowserSession()
    memory = InMemoryStore(max_entries=10)
    notifier = CollectingNotifier()
    portal = StubPortal(finish=True)
    controller = ManualPauseController()
    requested = controller.request_pause(
        reason="Admin requested pause",
        instructions="Take over via VNC",
    )
    assert requested is True

    orchestrator = Orchestrator(
        config=build_config(),
        llm=llm,
        browser=browser,
        memory=memory,
        notifier=notifier,
        user_portal=portal,
        manual_controller=controller,
    )
    success = orchestrator.run()
    assert success is True
    assert portal.request is not None
    assert portal.request.metadata.get("source") == "manual_pause"
    assert controller.get_active() is None


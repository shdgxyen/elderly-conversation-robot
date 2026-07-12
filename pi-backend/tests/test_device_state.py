from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.device import DeviceState, DeviceStateMachine
from app.device.device_state import (
    InvalidStateTransition,
    PrivacyConstraintError,
)


def test_all_spec_states_are_defined() -> None:
    assert {state.value for state in DeviceState} == {
        "BOOTING",
        "IDLE",
        "FACE_SCANNING",
        "USER_RECOGNIZED",
        "UNKNOWN_USER",
        "LISTENING",
        "THINKING",
        "SPEAKING",
        "CONFUSED",
        "COMFORT",
        "PRIVACY_MIC_OFF",
        "PRIVACY_CAMERA_OFF",
        "NETWORK_ERROR",
        "API_ERROR",
        "LOW_POWER",
    }


def test_normal_conversation_path_and_invalid_boot_transition() -> None:
    machine = DeviceStateMachine()

    with pytest.raises(InvalidStateTransition):
        machine.transition(DeviceState.SPEAKING)

    machine.transition(DeviceState.IDLE)
    machine.transition(DeviceState.LISTENING)
    machine.transition(DeviceState.THINKING)
    snapshot = machine.transition(DeviceState.SPEAKING)

    assert snapshot.state is DeviceState.SPEAKING
    assert [change.current_state for change in machine.history()] == [
        DeviceState.IDLE,
        DeviceState.LISTENING,
        DeviceState.THINKING,
        DeviceState.SPEAKING,
    ]


def test_physical_privacy_precedence_and_safe_resume() -> None:
    machine = DeviceStateMachine(DeviceState.IDLE)
    machine.transition(DeviceState.LISTENING)

    snapshot = machine.set_camera_blocked(True)
    # Camera privacy does not interrupt a microphone-only operation.
    assert snapshot.state is DeviceState.LISTENING
    assert snapshot.camera_blocked is True

    snapshot = machine.set_mic_muted(True)
    # Muting the microphone does immediately stop LISTENING.
    assert snapshot.state is DeviceState.PRIVACY_MIC_OFF
    assert snapshot.mic_muted is True
    assert snapshot.camera_blocked is True

    snapshot = machine.set_mic_muted(False)
    assert snapshot.state is DeviceState.PRIVACY_CAMERA_OFF

    snapshot = machine.set_camera_blocked(False)
    assert snapshot.state is DeviceState.IDLE
    assert snapshot.mic_muted is False
    assert snapshot.camera_blocked is False


def test_camera_privacy_allows_audio_conversation_but_blocks_face_scan() -> None:
    machine = DeviceStateMachine(DeviceState.IDLE)
    assert machine.set_camera_blocked(True).state is DeviceState.PRIVACY_CAMERA_OFF

    assert machine.handle_event("WAKE_BUTTON_PRESSED").state is DeviceState.LISTENING
    assert machine.transition(DeviceState.THINKING).state is DeviceState.THINKING
    assert machine.transition(DeviceState.SPEAKING).state is DeviceState.SPEAKING
    assert machine.transition(DeviceState.IDLE).state is DeviceState.PRIVACY_CAMERA_OFF
    with pytest.raises(PrivacyConstraintError):
        machine.transition(DeviceState.FACE_SCANNING, force=True)


def test_mic_privacy_allows_text_thinking_and_speaking_but_blocks_listening() -> None:
    machine = DeviceStateMachine(DeviceState.IDLE)
    assert machine.set_mic_muted(True).state is DeviceState.PRIVACY_MIC_OFF

    assert machine.transition(DeviceState.THINKING).state is DeviceState.THINKING
    assert machine.transition(DeviceState.SPEAKING).state is DeviceState.SPEAKING
    with pytest.raises(PrivacyConstraintError):
        machine.transition(DeviceState.LISTENING, force=True)
    assert machine.transition(DeviceState.IDLE).state is DeviceState.PRIVACY_MIC_OFF
    # Unmuting always returns to safe idle, never the previous sensitive action.
    assert machine.set_mic_muted(False).state is DeviceState.IDLE


def test_privacy_forbids_sensitive_operations_even_with_force() -> None:
    machine = DeviceStateMachine(DeviceState.IDLE)
    machine.set_mic_muted(True)

    with pytest.raises(PrivacyConstraintError):
        machine.transition(DeviceState.LISTENING, force=True)

    machine.set_mic_muted(False)
    machine.set_camera_blocked(True)
    with pytest.raises(PrivacyConstraintError):
        machine.transition(DeviceState.FACE_SCANNING, force=True)


def test_stop_while_private_changes_safe_resume_but_not_privacy_indicator() -> None:
    machine = DeviceStateMachine(DeviceState.IDLE)
    machine.set_mic_muted(True)

    snapshot = machine.handle_event("STOP_BUTTON_PRESSED")
    assert snapshot.state is DeviceState.PRIVACY_MIC_OFF

    assert machine.set_mic_muted(False).state is DeviceState.IDLE


@pytest.mark.parametrize(
    "initial_state",
    [DeviceState.NETWORK_ERROR, DeviceState.API_ERROR, DeviceState.LOW_POWER],
)
def test_wake_recovers_non_conversation_states(initial_state: DeviceState) -> None:
    machine = DeviceStateMachine(initial_state)

    assert machine.handle_event("WAKE_BUTTON_PRESSED").state is DeviceState.LISTENING


def test_stop_always_returns_to_safe_idle_visual() -> None:
    machine = DeviceStateMachine(DeviceState.NETWORK_ERROR)
    # The camera flag is independent and does not hide the active error.
    assert machine.set_camera_blocked(True).state is DeviceState.NETWORK_ERROR

    snapshot = machine.handle_event("STOP_BUTTON_PRESSED")
    assert snapshot.state is DeviceState.PRIVACY_CAMERA_OFF
    assert snapshot.camera_blocked is True


def test_identity_heartbeat_listener_and_thread_safety() -> None:
    machine = DeviceStateMachine(DeviceState.IDLE)
    changes = []
    machine.add_listener(changes.append)
    machine.transition(DeviceState.THINKING, reason="test")
    machine.set_current_user_id(" user-001 ")

    with ThreadPoolExecutor(max_workers=8) as executor:
        snapshots = list(executor.map(machine.record_heartbeat, range(100)))

    assert changes[0].state is DeviceState.THINKING
    assert changes[0].reason == "test"
    assert machine.current_user_id == "user-001"
    assert machine.last_heartbeat is not None
    assert machine.last_heartbeat_uptime_ms in range(100)
    assert all(snapshot.last_heartbeat is not None for snapshot in snapshots)
    assert machine.is_alive(timeout_seconds=5)


def test_async_facade_uses_the_same_safe_state() -> None:
    async def scenario() -> None:
        machine = DeviceStateMachine(DeviceState.IDLE)
        await machine.atransition(DeviceState.THINKING)
        await machine.atransition(DeviceState.SPEAKING)
        await machine.aset_current_user_id("user-async")
        await machine.arecord_heartbeat(42)
        assert machine.snapshot().state is DeviceState.SPEAKING
        assert machine.current_user_id == "user-async"

    asyncio.run(scenario())

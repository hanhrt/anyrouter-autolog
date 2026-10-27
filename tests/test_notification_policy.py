import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import checkin
from utils.config import AccountConfig


@pytest.fixture
def notification_run(monkeypatch, tmp_path):
	monkeypatch.chdir(tmp_path)
	monkeypatch.setattr(checkin, 'is_debug_enabled', lambda: False)
	monkeypatch.setattr(checkin.AppConfig, 'load_from_env', lambda: SimpleNamespace(providers={}))
	accounts = [AccountConfig(cookies={}, name='Test account')]
	monkeypatch.setattr(checkin, 'load_accounts_config', lambda: accounts)
	send = Mock()
	monkeypatch.setattr(checkin.notify, 'push_message', send)
	info = {'success': True, 'quota': 100.0, 'used_quota': 20.0, 'display': 'Balance: $100.00'}

	def run(mode=None, results=None, names=None):
		if mode is None:
			monkeypatch.delenv('NOTIFY_ALWAYS', raising=False)
		else:
			monkeypatch.setenv('NOTIFY_ALWAYS', mode)
		if names is not None:
			accounts[:] = [AccountConfig(cookies={}, name=name) for name in names]
		monkeypatch.setattr(
			checkin,
			'check_in_account',
			AsyncMock(side_effect=results or [(True, info, info)] * len(accounts)),
		)
		with pytest.raises(SystemExit) as exit_info:
			asyncio.run(checkin.main())
		return exit_info.value.code

	return run, send, info


@pytest.mark.parametrize('mode,expected_calls', [(None, 1), ('0', 1), ('1', 2), (' 1 ', 2)])
def test_repeated_success_respects_notification_mode(notification_run, mode, expected_calls):
	run, send, _ = notification_run
	assert run(mode) == 0
	assert run(mode) == 0
	assert send.call_count == expected_calls
	if expected_calls == 2:
		content = send.call_args.args[1]
		assert '今日已签到，无变化' in content
		assert 'Success: 1/1' in content


@pytest.mark.parametrize('mode', ['0', '1'])
def test_failures_notify_even_with_unchanged_balances(notification_run, mode):
	run, send, info = notification_run
	run('0')
	send.reset_mock()
	assert run(mode, [(False, info, info)]) == 1
	send.assert_called_once()
	assert '[FAIL] Test account' in send.call_args.args[1]


def test_balance_change_still_notifies_in_deduplicated_mode(notification_run):
	run, send, info = notification_run
	run('0')
	send.reset_mock()
	after = {**info, 'quota': 125.0}
	assert run('0', [(True, info, after)]) == 0
	send.assert_called_once()
	assert '签到获得: +$25.00' in send.call_args.args[1]


@pytest.mark.parametrize('before_available,after_available', [(False, True), (True, False), (False, False)])
def test_always_notify_includes_result_when_balance_details_are_unavailable(
	notification_run, before_available, after_available
):
	run, send, info = notification_run
	result = (True, info if before_available else None, info if after_available else None)
	assert run('1', [result]) == 0
	send.assert_called_once()
	assert '[SUCCESS] Test account' in send.call_args.args[1]
	assert 'Success: 1/1' in send.call_args.args[1]


def test_always_notify_includes_every_account_in_one_message(notification_run):
	run, send, _ = notification_run
	assert run('1', names=['Account', 'Account backup']) == 0
	send.assert_called_once()
	content = send.call_args.args[1]
	assert content.count('[CHECK-IN]') == 2
	assert '[CHECK-IN] Account backup' in content
	assert 'Success: 2/2' in content


def test_turning_off_always_notify_reuses_balance_history(notification_run):
	run, send, _ = notification_run
	run('1')
	send.reset_mock()
	assert run('0') == 0
	send.assert_not_called()

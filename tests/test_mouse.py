"""Tests for browser pointer and scrolling helpers."""

from bot.utils.mouse import (
    _clamp_point_to_viewport,
    _dom_mouse_path_click,
    _element_viewport_center,
    _uses_attached_chrome_debugger,
    _wheel_scroll,
    click_target_diagnostics,
    human_click,
    human_reading_scroll,
)


def test_clamp_point_to_viewport():
    assert _clamp_point_to_viewport((-10, 999), 120, 80) == (0, 79)
    assert _clamp_point_to_viewport((45, 60), 120, 80) == (45, 60)


def test_element_viewport_center_uses_bounding_client_rect(mocker):
    driver = mocker.Mock()
    element = mocker.Mock()
    driver.execute_script.return_value = {"x": 312, "y": 430}

    assert _element_viewport_center(driver, element) == (312, 430)
    assert "getBoundingClientRect" in driver.execute_script.call_args.args[0]
    assert driver.execute_script.call_args.args[1] is element


def test_uses_attached_chrome_debugger_detects_debugger_address(mocker):
    driver = mocker.Mock()
    driver.capabilities = {"goog:chromeOptions": {"debuggerAddress": "127.0.0.1:9222"}}

    assert _uses_attached_chrome_debugger(driver)


def test_wheel_scroll_uses_js_scroll_without_cdp(mocker):
    driver = mocker.Mock()
    sleep = mocker.patch("bot.utils.mouse.time.sleep")

    _wheel_scroll(driver, 240, 0.1)

    driver.execute_script.assert_called_once_with(
        "window.scrollBy({top: arguments[0], behavior: 'auto'});",
        240,
    )
    driver.execute_cdp_cmd.assert_not_called()
    sleep.assert_called_once_with(0.1)


def test_dom_mouse_path_click_dispatches_script(mocker):
    driver = mocker.Mock()
    element = mocker.Mock()

    _dom_mouse_path_click(driver, element, [(10, 20), (30, 40)])

    driver.execute_script.assert_called_once()
    assert "pointermove" in driver.execute_script.call_args.args[0]
    assert driver.execute_script.call_args.args[1] is element
    assert driver.execute_script.call_args.args[2] == [(10, 20), (30, 40)]


def test_click_target_diagnostics_can_skip_scroll(mocker):
    driver = mocker.Mock()
    element = mocker.Mock()

    click_target_diagnostics(driver, element, scroll=False)

    driver.execute_script.assert_called_once()
    assert driver.execute_script.call_args.args[1] is element
    assert driver.execute_script.call_args.args[2] is False


def test_human_reading_scroll_skims_down_then_back(mocker):
    driver = mocker.Mock()
    driver.execute_script.return_value = {
        "y": 100,
        "viewportHeight": 600,
        "documentHeight": 2400,
    }
    mocker.patch("bot.utils.mouse.random.randint", side_effect=[2, 160, 180, 1])
    mocker.patch("bot.utils.mouse.random.uniform", side_effect=[0.4, 0.5, 0.75, 0.3])
    wheel = mocker.patch("bot.utils.mouse._wheel_scroll")

    movements = human_reading_scroll(driver)

    assert movements == [160, 180, -135]
    assert wheel.call_args_list == [
        mocker.call(driver, 160, 0.4),
        mocker.call(driver, 180, 0.5),
        mocker.call(driver, -135, 0.3),
    ]


def test_human_reading_scroll_skips_short_pages(mocker):
    driver = mocker.Mock()
    driver.execute_script.return_value = {
        "y": 0,
        "viewportHeight": 700,
        "documentHeight": 760,
    }
    wheel = mocker.patch("bot.utils.mouse._wheel_scroll")

    assert human_reading_scroll(driver) == []
    wheel.assert_not_called()


def test_human_click_scrolls_before_diagnostics_in_human_mode(mocker):
    driver = mocker.Mock()
    element = mocker.Mock()
    reading_scroll = mocker.patch("bot.utils.mouse.human_reading_scroll")
    scroll = mocker.patch("bot.utils.mouse.human_scroll_to_element")
    diagnostics = mocker.patch(
        "bot.utils.mouse.click_target_diagnostics",
        return_value={"ok": True},
    )
    pointer_click = mocker.patch("bot.utils.mouse._pointer_click")
    mocker.patch("bot.utils.mouse.HAS_BEZIER", False)

    result = human_click(driver, element, enabled=True)

    assert result == {"ok": True}
    reading_scroll.assert_called_once_with(driver)
    scroll.assert_called_once_with(driver, element)
    diagnostics.assert_called_once_with(driver, element, scroll=False)
    pointer_click.assert_called_once_with(driver, element, 0.05)


def test_human_click_uses_dom_path_for_attached_debugger(mocker):
    driver = mocker.Mock()
    driver.capabilities = {"goog:chromeOptions": {"debuggerAddress": "127.0.0.1:9222"}}
    driver.execute_script.side_effect = [1280, 720, {"x": 355, "y": 477}]
    element = mocker.Mock()
    mocker.patch("bot.utils.mouse.human_reading_scroll")
    mocker.patch("bot.utils.mouse.human_scroll_to_element")
    mocker.patch(
        "bot.utils.mouse.click_target_diagnostics",
        return_value={"ok": True},
    )
    mocker.patch("bot.utils.mouse.HAS_BEZIER", True)
    mocker.patch(
        "bot.utils.mouse._bezier_curve_points",
        return_value=[(100, 100), (355, 477)],
    )
    dom_click = mocker.patch("bot.utils.mouse._dom_mouse_path_click")
    pointer_click = mocker.patch("bot.utils.mouse._pointer_click")

    result = human_click(driver, element, enabled=True)

    assert result == {"ok": True}
    dom_click.assert_called_once_with(driver, element, [(100, 100), (355, 477)])
    pointer_click.assert_not_called()


def test_human_click_keeps_legacy_scroll_when_human_mode_disabled(mocker):
    driver = mocker.Mock()
    element = mocker.Mock()
    reading_scroll = mocker.patch("bot.utils.mouse.human_reading_scroll")
    scroll = mocker.patch("bot.utils.mouse.human_scroll_to_element")
    diagnostics = mocker.patch(
        "bot.utils.mouse.click_target_diagnostics",
        return_value={"ok": True},
    )
    pointer_click = mocker.patch("bot.utils.mouse._pointer_click")

    result = human_click(driver, element, enabled=False)

    assert result == {"ok": True}
    reading_scroll.assert_not_called()
    scroll.assert_not_called()
    diagnostics.assert_called_once_with(driver, element, scroll=True)
    pointer_click.assert_called_once_with(driver, element, 0.05)

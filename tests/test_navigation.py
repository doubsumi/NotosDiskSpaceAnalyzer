"""NavigationService 单元测试（V2）。

覆盖：
    history / back / home / navigate_to / current path
"""

from __future__ import annotations

from src.services.navigation_service import NavigationService


def test_initial_state():
    service = NavigationService()
    assert service.current_path is None
    assert service.history == []


def test_navigate_builds_history():
    service = NavigationService()
    service.navigate_to("A")
    service.navigate_to("B")
    service.navigate_to("C")

    assert service.current_path == "C"
    assert service.history == ["A", "B"]


def test_go_back_pops_history():
    service = NavigationService()
    service.navigate_to("A")
    service.navigate_to("B")

    assert service.go_back() == "A"
    assert service.current_path == "A"
    assert service.history == []


def test_go_back_at_root_returns_none():
    service = NavigationService()
    assert service.go_back() is None
    assert service.current_path is None


def test_go_home_clears_state():
    service = NavigationService()
    service.navigate_to("A")
    service.navigate_to("B")
    service.go_home()

    assert service.current_path is None
    assert service.history == []


def test_display_text():
    service = NavigationService()
    assert service.get_current_path_display() == "磁盘根目录"

    service.navigate_to("A")
    assert "A" in service.get_current_path_display()

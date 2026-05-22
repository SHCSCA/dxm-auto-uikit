from src.services.publish_guard import PublishGuardService


def test_allows_save_without_publish_signals():
    guard = PublishGuardService()

    result = guard.check(
        intended_action='save',
        target_text='保存',
        current_url='https://seller.example.com/product/edit',
        visible_texts=['商品信息', '保存草稿'],
        modal_texts=[],
        network_urls=['https://seller.example.com/api/product/save'],
    )

    assert result['allowed'] is True
    assert result['risk_level'] == 'low'
    assert result['error_code'] is None
    assert result['reasons'] == []


def test_rejects_publish_button_target():
    guard = PublishGuardService()

    result = guard.check(
        intended_action='click',
        target_text='立即发布',
        current_url='https://seller.example.com/product/edit',
        visible_texts=['商品信息', '保存'],
        modal_texts=[],
        network_urls=[],
    )

    assert result['allowed'] is False
    assert result['risk_level'] == 'critical'
    assert result['error_code'] == 'E999'
    assert any('target_text' in reason for reason in result['reasons'])


def test_rejects_save_when_publish_confirmation_modal_is_visible():
    guard = PublishGuardService()

    result = guard.check(
        intended_action='save',
        target_text='保存',
        current_url='https://seller.example.com/product/edit',
        visible_texts=['商品信息', '保存'],
        modal_texts=['确认发布该商品吗？', '取消', '确认发布'],
        network_urls=[],
    )

    assert result['allowed'] is False
    assert result['risk_level'] == 'critical'
    assert result['error_code'] == 'E999'
    assert any('modal_texts' in reason for reason in result['reasons'])


def test_rejects_publish_network_url():
    guard = PublishGuardService()

    result = guard.check(
        intended_action='save',
        target_text='保存',
        current_url='https://seller.example.com/product/edit',
        visible_texts=['商品信息', '保存'],
        modal_texts=[],
        network_urls=['https://seller.example.com/api/items/submitPublish'],
    )

    assert result['allowed'] is False
    assert result['risk_level'] == 'critical'
    assert result['error_code'] == 'E999'
    assert any('network_urls' in reason for reason in result['reasons'])


def test_rejects_save_when_visible_publish_button_exists():
    guard = PublishGuardService()

    result = guard.check(
        intended_action='save',
        target_text='保存',
        current_url='https://seller.example.com/product/edit',
        visible_texts=['保存', '立即发布'],
        modal_texts=[],
        network_urls=[],
    )

    assert result['allowed'] is False
    assert result['error_code'] == 'E999'
    assert any('visible_texts' in reason for reason in result['reasons'])


def test_allows_save_success_text_that_mentions_pending_publish_status():
    guard = PublishGuardService()

    result = guard.check(
        intended_action='save',
        target_text='保存',
        current_url='https://seller.example.com/product/edit',
        visible_texts=['保存'],
        modal_texts=['您的产品编辑成功，产品已保存到「待发布」'],
        network_urls=['https://seller.example.com/api/product/save'],
    )

    assert result['allowed'] is True
    assert result['reasons'] == []


def test_rejects_move_to_pending_publish_actions():
    guard = PublishGuardService()

    result = guard.check(
        intended_action='save',
        target_text='保存并移入待发布',
        current_url='https://seller.example.com/product/edit',
        visible_texts=['移入待发布'],
    )

    assert result['allowed'] is False
    assert result['error_code'] == 'E999'

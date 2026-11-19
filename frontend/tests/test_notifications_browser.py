from pathlib import Path

import pytest


@pytest.mark.parametrize('width', [1280, 390])
def test_notifications_float_dismiss_and_preserve_inline_feedback(width):
    from playwright.sync_api import sync_playwright, expect

    assets = Path(__file__).resolve().parents[1] / 'static'
    with sync_playwright() as engine:
        options = {'headless': True}
        if not Path(engine.chromium.executable_path).exists():
            options['channel'] = 'msedge'
        browser = engine.chromium.launch(**options)
        page = browser.new_page(viewport={'width': width, 'height': 850})
        page.set_content('''<div data-entry-success>HFL entry created successfully.</div>
          <p id="role-status"></p><p role="alert">Title is required.</p>
          <main style="height:2000px">Page content</main><dialog><form>Editor</form></dialog>''')
        page.add_style_tag(path=str(assets / 'css/notifications.css'))
        page.add_script_tag(path=str(assets / 'js/notifications.js'))
        toast = page.locator('.notification-toast')
        expect(toast).to_contain_text('HFL entry created successfully.')
        expect(page.locator('[data-entry-success]')).to_be_hidden()
        expect(page.locator('[role="alert"]')).to_be_visible()
        before = toast.bounding_box()
        page.evaluate('window.scrollTo(0, 600)')
        assert toast.bounding_box()['y'] == before['y']
        assert before['x'] >= 0 and before['x'] + before['width'] <= width
        toast.get_by_role('button', name='Dismiss notification').click()
        expect(toast).to_have_count(0)
        # The same reusable status node can report the same result repeatedly.
        for _ in range(2):
            page.evaluate("""() => {const status=document.querySelector('#role-status');
              status.classList.add('role-save-notice');status.textContent='Saved.';}""")
            expect(toast).to_contain_text('Saved.')
            toast.get_by_role('button', name='Dismiss notification').click()
            expect(toast).to_have_count(0)
        page.evaluate("""() => {const dialog=document.querySelector('dialog');dialog.showModal();
          const notice=document.createElement('div');notice.className='corpus-action-toast';
          notice.textContent='Saved with a warning.';notice.setAttribute('data-notification-persistent','');
          dialog.append(notice);} """)
        expect(page.locator('dialog .notification-toast')).to_be_visible()
        page.screenshot(path=str(Path.cwd() / '.tmp' / f'notification-preview-{width}.png'))
        page.evaluate("document.querySelector('dialog').close()")
        page.clock.install()
        page.evaluate("() => { HarqisToast.show('Temporary confirmation.'); }")
        temporary = page.locator('body > .notification-stack .notification-toast')
        temporary.hover()
        page.clock.fast_forward(7000)
        expect(temporary).to_be_visible()
        page.mouse.move(0, 0)
        page.clock.fast_forward(7000)
        expect(temporary).to_have_count(0)
        browser.close()

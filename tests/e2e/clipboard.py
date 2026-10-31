"""Copy, cut and paste of clips and Paste attributes. A hook text and a sticker copied with Ctrl+C go 10 s later with
Ctrl+V, each on the track it came from, as one undo step, and the export draws them there as at their first place; the
context menu gives a plain text the hook's look and keeps its words, as one undo step; the AI lock refuses cutting and
pasting with its notice; Ctrl+C in a text field or in the transcript copies no clip; Ctrl+X cuts; and the copied hook
and sticker paste into another project, bringing the sticker's file in the same undo step and drawn there as in the first
project."""
import json, subprocess, time
from pathlib import Path

import numpy as np
from PIL import Image

from e2e.harness import AI_EDITING, CLI, Bridge, changed_share, export, flow, wait
from e2e.layout import resize

PROJECT = 'return window.__nuzky.store.getState().snap.project'
CLICK = "const el = document.querySelector(arguments[0]); if (!el) return false; el.click(); return true;"
RIGHT_CLICK = """const c = document.querySelector(`[data-clip-id="${arguments[0]}"]`); const b = c.getBoundingClientRect();
c.dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, cancelable: true, clientX: b.left + 4, clientY: b.top + 4}));"""
# An item is its icon, its label and its shortcut.
MENU = """return [...document.querySelectorAll('[role=menu] [role=menuitem]')].map((i) =>
    ({label: i.children[1].textContent, disabled: i.getAttribute('aria-disabled') === 'true', reason: i.title}));"""
PICK = """const item = [...document.querySelectorAll('[role=menu] [role=menuitem]')].find((i) => i.children[1].textContent === arguments[0]);
if (!item) return false; item.click(); return true;"""
NOTHING_COPIED = 'Nothing to paste. Copy clips with Ctrl+C first.'


def project(r):
    return r.s.run(PROJECT, retries=3)


def clips(r):
    return [(i, c) for i, t in enumerate(project(r)['tracks']) for c in t['clips']]


def clip(r, clip_id):
    return next((c for _, c in clips(r) if c['id'] == clip_id), None)


def select(r, ids):
    r.s.run('document.activeElement?.blur(); window.__nuzky.store.getState().select(arguments[0])', ids)


def toast(r, text):
    """The toast's action label, '' for one without, None when there is no such toast."""
    return r.s.run("const t = window.__nuzky.store.getState().toasts.find((t) => t.text === arguments[0]);"
                   "return t ? (t.action?.label ?? '') : null;", text)


def frame(r, name, at_us):
    """The renderer's frame from the open project's saved file, once the file holds what the editor shows."""
    # Not r.saved_project(), which takes any project file once a second project exists.
    saved = Path(r.s.run('return window.__nuzky.store.getState().snap.path'))
    key = lambda p: [(c['id'], c['startUs'], c['content'].get('style')) for t in p['tracks'] for c in t['clips']]
    wait(lambda: key(json.loads(saved.read_text())) == key(project(r)), 10)
    path = r.work / f'{name}.png'
    subprocess.run([str(CLI), 'frame', str(saved), f'{at_us / 1e6:.6f}', str(path), '720'], env=r.env, check=True,
                   capture_output=True)
    return path


def yellow(path):
    """Share of the picture in the Highlight text's yellow box; the blue background and white text have none."""
    a = np.asarray(Image.open(path).convert('RGB'), dtype=int)
    return float(((a[..., 0] > 200) & (a[..., 1] > 170) & (a[..., 2] < 90)).mean())


def bands(a, b):
    """Changed share in the middle, where the text is, and in the lower band, where the sticker is."""
    first, second = (Image.open(x) for x in (a, b))
    box = lambda image, top, bottom: image.crop((0, int(image.height * top), image.width, int(image.height * bottom)))
    return [round(changed_share(box(first, t, u), box(second, t, u)), 4) for t, u in ((0.42, 0.58), (0.7, 0.9))]


def same(a, b):
    """Two clips alike but for their id and start."""
    strip = lambda c: {k: v for k, v in c.items() if k not in ('id', 'startUs')}
    return strip(a) == strip(b)


@flow('clipboard', 'Ctrl+C and Ctrl+V put a hook text and a sticker 10 s later on their own tracks as one undo step, '
      'drawn there in the export as at their first place; Paste attributes from the context menu gives a plain text the '
      "hook's look as one undo step; the AI lock refuses cutting and pasting; Ctrl+C in a text field or the transcript "
      'copies no clip; Ctrl+X cuts; the copies paste into another project with their media as one undo step')
def clipboard_flow(r):
    # A still background, so a frame 10 s later differs only by what lies over it.
    still = r.work / 'still.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=0x203040:s=1080x1920:r=30:d=16',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(still)], check=True)
    r.import_media(still)
    r.add_clip('still.mp4')
    r.s.run(CLICK, '[role=tablist][aria-label=Library] [data-tab="text"]')
    r.s.run(CLICK, '#text-tab-text')
    r.seek(1_000_000)
    r.s.run(CLICK, 'button[title=\'Add "Highlight" text at the playhead\']')
    hook = wait(lambda: next((c for _, c in clips(r) if c['content'].get('text') == 'Highlight'), None), 5)
    r.seek(2_000_000)
    r.s.run(CLICK, '#text-tab-stickers')
    wait(lambda: r.s.run("return !!document.querySelector('[data-sticker=\"arrow\"] img')"), 10)
    r.s.run(CLICK, '[data-sticker="arrow"]')
    sticker = wait(lambda: next((c for i, c in clips(r) if i > 0 and c['content']['type'] == 'media'), None), 10)
    if not r.check('a Highlight text at 1 s and an arrow sticker at 2 s', hook and sticker, clips(r)):
        return
    # Lower down, so the text's box does not hide the arrow.
    r.s.call("window.__nuzky.store.getState().edit({type: 'updateClip', clipId: arguments[0], transform: {...arguments[1], y: 0.3}})",
             sticker['id'], sticker['content']['transform'])
    sticker = wait(lambda: (c := clip(r, sticker['id'])) and abs(c['content']['transform']['y'] - 0.3) < 1e-6 and c, 5)
    tracks = {c['id']: i for i, c in clips(r)}
    empty = frame(r, 'engine-12.5s-empty', 12_500_000)

    before = project(r)
    select(r, [hook['id'], sticker['id']])
    r.key('c', ctrlKey=True)
    r.check('Ctrl+C says two clips were copied and changes nothing',
            wait(lambda: toast(r, '2 clips copied') == '', 5) and project(r) == before, r.state()['toasts'])
    known = {c['id'] for _, c in clips(r)}
    r.seek(11_000_000)
    r.key('v', ctrlKey=True)
    pasted = wait(lambda: (new := [(i, c) for i, c in clips(r) if c['id'] not in known]) and len(new) == 2 and new, 5) or []
    placed = sorted((c['startUs'], i, c['content']['type']) for i, c in pasted)
    r.check('Ctrl+V pastes them 10 s later, each on the track it came from',
            placed == [(11_000_000, tracks[hook['id']], 'text'), (12_000_000, tracks[sticker['id']], 'media')], placed)
    copies = sorted((c for _, c in pasted), key=lambda c: c['startUs'])
    r.check('the copies are the clips as copied, with new ids',
            len(copies) == 2 and same(copies[0], hook) and same(copies[1], clip(r, sticker['id'])), copies)
    r.check('no track was added', len(project(r)['tracks']) == len(before['tracks']))
    selected = r.s.run('return window.__nuzky.store.getState().selection')
    r.check('the pasted clips are selected', sorted(selected) == sorted(c['id'] for c in copies), selected)
    r.shot('pasted')
    r.key('z', ctrlKey=True)
    r.check('one Ctrl+Z takes both back', wait(lambda: project(r)['tracks'] == before['tracks'], 5))
    r.key('z', ctrlKey=True, shiftKey=True)
    r.check('Ctrl+Shift+Z pastes them again', wait(lambda: len(clips(r)) == len(known) + 2, 5))

    # The renderer and the export draw them 10 s later as at their first place.
    first, later = frame(r, 'engine-2.5s', 2_500_000), frame(r, 'engine-12.5s', 12_500_000)
    r.check('the renderer draws the text and the arrow at 12.5 s as the originals at 2.5 s',
            all(x < 0.002 for x in bands(first, later)) and all(x > 0.01 for x in bands(empty, later)),
            {'from 2.5 s': bands(first, later), 'from the empty frame': bands(empty, later)})
    video = export(r, 'clipboard.mp4')
    exported = r.work / 'export-12.5s.png'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(video), '-vf', 'select=eq(n\\,375)', '-frames:v', '1', '-update', '1',
                    str(exported)], check=True)
    r.shots.append(exported.name)
    r.check('the exported frame at 12.5 s shows the text and the arrow as the frame at 2.5 s',
            all(x < 0.002 for x in bands(first, exported)) and all(x > 0.01 for x in bands(empty, exported)),
            {'from 2.5 s': bands(first, exported), 'from the empty frame': bands(empty, exported)})

    # The hook's look onto a plain text, from the context menu.
    r.s.run(CLICK, '#text-tab-text')
    r.seek(7_000_000)
    r.s.run(CLICK, 'button[title=\'Add "Plain" text at the playhead\']')
    plain = wait(lambda: next((c for _, c in clips(r) if c['content'].get('text') == 'Plain text'), None), 5)
    if not r.check('a Plain text at 7 s', plain, clips(r)):
        return
    unstyled = frame(r, 'engine-plain', 8_000_000)
    select(r, [hook['id']])
    r.key('c', ctrlKey=True)
    before = project(r)
    r.s.run(RIGHT_CLICK, plain['id'])
    menu = wait(lambda: r.s.run(MENU), 3) or []
    r.shot('context-menu')
    r.check('right-clicking the plain text offers Cut, Copy, Paste at playhead and Paste attributes',
            all(any(i['label'] == l and not i['disabled'] for i in menu) for l in ('Cut', 'Copy', 'Paste at playhead', 'Paste attributes')),
            menu)
    r.s.run(PICK, 'Paste attributes')
    styled = wait(lambda: (c := clip(r, plain['id'])) and c['content']['style'] == hook['content']['style'] and c, 5)
    r.check("Paste attributes gives the plain text the hook's style, keeping its words, place and length",
            styled and styled['content']['text'] == 'Plain text' and (styled['startUs'], styled['durationUs']) == (plain['startUs'], plain['durationUs']),
            styled or clip(r, plain['id']))
    r.check('a toast says so and offers Undo', toast(r, 'Attributes pasted to 1 clip') == 'Undo', r.state()['toasts'])
    restyled = frame(r, 'engine-restyled', 8_000_000)
    r.shots.append(restyled.name)
    r.check("the plain text now draws in the hook's yellow box", yellow(unstyled) < 0.001 and yellow(restyled) > 0.01,
            (round(yellow(unstyled), 4), round(yellow(restyled), 4)))
    r.key('z', ctrlKey=True)
    r.check('one Ctrl+Z gives the text its own look back and changes nothing else', wait(lambda: project(r)['tracks'] == before['tracks'], 5))
    r.key('z', ctrlKey=True, shiftKey=True)
    r.check('Ctrl+Shift+Z pastes the look again', wait(lambda: clip(r, plain['id'])['content']['style'] == hook['content']['style'], 5))

    # Under the AI lock copying works, cutting and pasting are refused with the notice.
    bridge = Bridge(r, r.saved_project())
    try:
        run = bridge.call('begin_run', {'label': 'Clipboard'})['run_id']
        r.check('the app shows the AI lock', wait(lambda: r.state()['aiRun'], 5))
        locked = project(r)
        select(r, [hook['id']])
        r.key('c', ctrlKey=True)
        r.check('copying still works', wait(lambda: toast(r, 'Clip copied') == '', 3), r.state()['toasts'])
        for key, modifiers in (('x', {}), ('v', {}), ('v', {'altKey': True, 'code': 'KeyV'})):
            r.key(key, ctrlKey=True, **modifiers)
        time.sleep(1)
        notices = [t for t in r.state()['toasts'] if t['text'] == AI_EDITING]
        r.check('Ctrl+X, Ctrl+V and Ctrl+Alt+V change nothing and show the AI notice once', project(r) == locked and len(notices) == 1,
                r.state()['toasts'])
        r.s.run(RIGHT_CLICK, hook['id'])
        menu = {i['label']: i for i in wait(lambda: r.s.run(MENU), 3) or []}
        r.check('the menu disables Cut, Paste and Paste attributes with the reason and keeps Copy',
                all(menu.get(l, {}).get('reason') == AI_EDITING and menu[l]['disabled'] for l in ('Cut', 'Paste at playhead', 'Paste attributes'))
                and not menu.get('Copy', {'disabled': True})['disabled'], menu)
        r.key('Escape')
        bridge.call('end_run', {'run_id': run, 'action': 'keep'})
        r.check('the lock ends with the run', wait(lambda: not r.state()['aiRun'], 5))
    finally:
        bridge.close()

    # Ctrl+C in the Text field copies its words, not the clip, so Ctrl+V still pastes the sticker copied before.
    select(r, [sticker['id']])
    r.key('c', ctrlKey=True)
    select(r, [plain['id']])
    focused = wait(lambda: r.s.run("const f = document.querySelector('textarea[aria-label=\"Text\"]'); if (!f) return false;"
                                   "f.focus(); f.select(); return document.activeElement === f;"), 5)
    r.key('c', ctrlKey=True)
    r.s.run('document.activeElement.blur()')
    known = {c['id'] for _, c in clips(r)}
    r.seek(6_000_000)
    r.key('v', ctrlKey=True)
    new = wait(lambda: [c for _, c in clips(r) if c['id'] not in known], 5) or []
    r.check('Ctrl+C in the Text field copied no clip: Ctrl+V pastes the sticker',
            focused and len(new) == 1 and new[0]['content'].get('assetId') == sticker['content']['assetId'] and new[0]['startUs'] == 6_000_000, new)

    # Ctrl+X cuts with Undo in its toast.
    select(r, [new[0]['id']] if new else [])
    r.key('x', ctrlKey=True)
    r.check('Ctrl+X removes the clip and the toast offers Undo',
            wait(lambda: not clip(r, new[0]['id']) if new else False, 5) and toast(r, 'Clip cut') == 'Undo', r.state()['toasts'])
    r.key('z', ctrlKey=True)
    r.check('Ctrl+Z brings it back', wait(lambda: clip(r, new[0]['id']) if new else False, 5))
    # Ctrl+V pressed right after Ctrl+X pastes what was just cut, not the sticker copied before.
    select(r, [plain['id']])
    r.s.run("for (const key of ['x', 'v']) document.body.dispatchEvent(new KeyboardEvent('keydown', {key, ctrlKey: true, bubbles: true, cancelable: true}));")
    moved = wait(lambda: not clip(r, plain['id']) and [c for _, c in clips(r) if c['content'].get('text') == 'Plain text'], 5) or []
    r.check('Ctrl+X and Ctrl+V at once move the plain text to the playhead', [c['startUs'] for c in moved] == [6_000_000],
            [(c['startUs'], c['content'].get('text') or c['content'].get('assetId')) for _, c in clips(r)])

    # In the transcript the keys paste nothing.
    r.s.run(CLICK, '[role=tablist][aria-label=Library] [data-tab="transcript"]')
    in_transcript = wait(lambda: r.s.run("const b = document.querySelector('#library-panel-transcript button'); if (!b) return false;"
                                         "b.focus(); return document.activeElement === b;"), 5)
    count = len(clips(r))
    r.key('v', ctrlKey=True)
    time.sleep(1)
    r.check('Ctrl+V in the transcript pastes nothing', in_transcript and len(clips(r)) == count, (in_transcript, len(clips(r)), count))
    r.check('no error toast', not r.errors(), r.errors())

    # The clipboard keeps its clips in another project: pasted there, they bring the media they use, as one undo step.
    select(r, [hook['id'], sticker['id']])
    r.key('c', ctrlKey=True)
    wait(lambda: toast(r, '2 clips copied') == '', 5)
    arrow = next(a for a in project(r)['assets'] if a['id'] == sticker['content']['assetId'])
    epoch = r.state()['epoch']
    r.s.call('window.__nuzky.newProjectFromMedia(arguments[0])', [str(still)])
    r.check('a new project opens in the editor', wait(lambda: r.state()['epoch'] != epoch
                                                      and r.s.run('return window.__nuzky.store.getState().view') == 'editor', 15))
    r.s.run('document.activeElement?.blur()')
    before = project(r)
    r.check("the new project does not have the arrow's file", all(a['path'] != arrow['path'] for a in before['assets']), before['assets'])
    known = {c['id'] for _, c in clips(r)}
    r.seek(3_000_000)
    r.key('v', ctrlKey=True)
    pasted = wait(lambda: (new := [c for _, c in clips(r) if c['id'] not in known]) and len(new) == 2 and new, 5) or []
    text = next((c for c in pasted if c['content']['type'] == 'text'), None)
    media = next((c for c in pasted if c['content']['type'] == 'media'), None)
    r.check('Ctrl+V there pastes the hook and the arrow at the playhead, keeping their offset and their look',
            text and media and (text['startUs'], media['startUs']) == (3_000_000, 4_000_000)
            and text['content']['style'] == hook['content']['style'] and media['content']['transform'] == sticker['content']['transform'],
            pasted)
    added = [a for a in project(r)['assets'] if a['path'] == arrow['path']]
    r.check("the arrow's file came along under the id its clip names, the file where it was",
            len(added) == 1 and media and media['content']['assetId'] == added[0]['id'] and Path(arrow['path']).is_file(), (added, media))
    r.shot('pasted-other-project')
    later = frame(r, 'other-project-4.5s', 4_500_000)
    r.check('the renderer draws the hook and the arrow there as in the first project',
            all(x < 0.002 for x in bands(first, later)) and all(x > 0.01 for x in bands(empty, later)),
            {'from the first project': bands(first, later), 'from the empty frame': bands(empty, later)})
    r.key('z', ctrlKey=True)
    r.check("one Ctrl+Z takes the clips and the arrow's file out again",
            wait(lambda: (p := project(r))['tracks'] == before['tracks'] and p['assets'] == before['assets'], 5),
            [a['path'] for a in project(r)['assets']])
    r.key('z', ctrlKey=True, shiftKey=True)
    wait(lambda: len(clips(r)) == len(known) + 2, 5)
    assets = project(r)['assets']
    known = {c['id'] for _, c in clips(r)}
    r.seek(8_000_000)
    r.key('v', ctrlKey=True)
    again = wait(lambda: (new := [c for _, c in clips(r) if c['id'] not in known]) and len(new) == 2 and new, 5) or []
    r.check('pasting again uses the file the project now has, adding no media',
            project(r)['assets'] == assets and any(c['content'].get('assetId') == added[0]['id'] for c in again) if added else False,
            [a['path'] for a in project(r)['assets']])
    r.check('no error toast in the other project', not r.errors(), r.errors())

    # The menu in the smallest window, offering the copies.
    resize(r, 1024, 640)
    r.s.run(RIGHT_CLICK, r.track()[0]['id'])
    menu = {i['label']: i for i in wait(lambda: r.s.run(MENU), 3) or []}
    paste = next((i for label, i in menu.items() if label.startswith('Paste') and label.endswith('at playhead')), None)
    r.check('there Paste offers the clips copied in the other project', paste and paste['label'] == 'Paste 2 clips at playhead'
            and not paste['disabled'], menu)
    r.shot('context-menu-1024')

"""Saved elements. A hook text and a sticker with a fade, saved from the clip context menu, show in the Saved tab with
the renderer's picture of them and are kept beside the projects; in another project a click puts both at the playhead
as one undo step, bringing the sticker's file along, and the renderer draws them there as in the first project; the
menu renames and deletes an element, and the toast's Undo puts it back."""
import json, subprocess
from pathlib import Path

from e2e.clipboard import CLICK, MENU, PICK, RIGHT_CLICK, bands, clip, clips, frame, project, select
from e2e.harness import flow, wait
from e2e.layout import resize

FILL = """const f = document.querySelector('input[aria-label="Element name"]'); if (!f) return false; f.focus();
Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(f, arguments[0]);
f.dispatchEvent(new Event('input', {bubbles: true})); return true;"""
TILES = """return [...document.querySelectorAll('[data-element]')].map((t) =>
    ({name: t.dataset.element, picture: t.querySelector('img')?.src.startsWith('data:image/png') ?? false}));"""
TILE_CLICK = "const t = document.querySelector(`[data-element=\"${arguments[0]}\"] button`); if (!t) return false; t.click(); return true;"
TILE_MENU = """const t = document.querySelector(`[data-element="${arguments[0]}"] button`); const b = t.getBoundingClientRect();
t.dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, cancelable: true, clientX: b.left + 4, clientY: b.top + 4}));"""
SAVED_SHOWN = """return window.__nuzky.store.getState().panelTab === 'media'
    && document.querySelector('[role=tablist][aria-label=Media] [aria-selected=true]')?.textContent === 'Saved';"""
OPEN_SAVED = """window.__nuzky.store.setState({panelTab: 'media'}); return true;"""
SAVED_TAB = "[role=tablist][aria-label=Media] [data-tab=\"saved\"]"
UNDO_TOAST = """const t = window.__nuzky.store.getState().toasts.find((t) => t.text === arguments[0]);
if (!t?.action) return false; t.action.run(); return true;"""


def stored(r):
    """The saved elements as the file beside the projects holds them."""
    path = r.work / 'data/nuzky/elements.json'
    return json.loads(path.read_text()) if path.exists() else []


def name_it(r, name):
    filled = wait(lambda: r.s.run(FILL, name), 5)
    r.key('Enter')
    return filled


@flow('saved_elements', 'Save as element keeps a hook text and a faded sticker beside the projects with their picture '
      'in the Saved tab; in another project a click puts both at the playhead with the sticker file as one undo step, '
      'drawn as in the first project; Rename and Delete with Undo')
def saved_elements_flow(r):
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
    # Lower down, so the text's box does not hide the arrow, and fading in.
    edit = "window.__nuzky.store.getState().edit(arguments[0])"
    r.s.call(edit, {'type': 'updateClip', 'clipId': sticker['id'], 'transform': {**sticker['content']['transform'], 'y': 0.3}})
    r.s.call(edit, {'type': 'setAnimation', 'clipId': sticker['id'], 'slot': 'in', 'animation': {'kind': 'fade', 'durationUs': 400_000}})
    sticker = wait(lambda: (c := clip(r, sticker['id'])) and c['animIn'] and abs(c['content']['transform']['y'] - 0.3) < 1e-6 and c, 5)
    first = frame(r, 'first-2.5s', 2_500_000)
    empty = frame(r, 'first-12.5s-empty', 12_500_000)
    arrow = next(a for a in project(r)['assets'] if a['id'] == sticker['content']['assetId'])

    # Save as element from the context menu, named in the Saved tab.
    select(r, [hook['id'], sticker['id']])
    r.s.run(RIGHT_CLICK, sticker['id'])
    menu = wait(lambda: r.s.run(MENU), 3) or []
    r.check('the context menu offers Save 2 clips as element…', any(i['label'] == 'Save 2 clips as element…' and not i['disabled'] for i in menu), menu)
    r.s.run(PICK, 'Save 2 clips as element…')
    tab = wait(lambda: r.s.run(SAVED_SHOWN), 3)
    suggested = r.s.run("return document.querySelector('input[aria-label=\"Element name\"]')?.value ?? null")
    r.check("the Media tab opens on Saved with the name field, named after the clips", tab and suggested == '2 clips', suggested)
    name_it(r, 'Hook and arrow')
    saved = wait(lambda: (s := stored(r)) and s, 10) or []
    element = saved[0] if saved else {}
    r.check('the element is kept beside the projects with both clips and only the arrow file',
            len(saved) == 1 and element['name'] == 'Hook and arrow' and len(element['clips']) == 2
            and [a['path'] for a in element['assets']] == [arrow['path']], saved)
    picture = r.work / f"data/nuzky/elements/{element.get('id')}.png"
    tiles = wait(lambda: (t := r.s.run(TILES)) and t[0]['picture'] and t, 10) or []
    r.check('Saved shows it with the picture the renderer drew', picture.is_file()
            and tiles == [{'name': 'Hook and arrow', 'picture': True}], tiles)
    r.shot('saved-tab')

    # In another project, a click puts it at the playhead with the arrow's file, as one undo step.
    epoch = r.state()['epoch']
    r.s.call('window.__nuzky.newProjectFromMedia(arguments[0])', [str(still)])
    r.check('a new project opens in the editor', wait(lambda: r.state()['epoch'] != epoch
                                                      and r.s.run('return window.__nuzky.store.getState().view') == 'editor', 15))
    r.s.run(OPEN_SAVED)
    wait(lambda: r.s.run(CLICK, SAVED_TAB), 3)
    r.check('Saved lists the element in the other project too',
            wait(lambda: r.s.run(TILES) == [{'name': 'Hook and arrow', 'picture': True}], 10), r.s.run(TILES))
    before = project(r)
    known = {c['id'] for _, c in clips(r)}
    r.seek(3_000_000)
    r.s.run(TILE_CLICK, 'Hook and arrow')
    placed = wait(lambda: (new := [c for _, c in clips(r) if c['id'] not in known]) and len(new) == 2 and new, 5) or []
    text = next((c for c in placed if c['content']['type'] == 'text'), None)
    media = next((c for c in placed if c['content']['type'] == 'media'), None)
    r.check('a click puts the hook and the arrow at the playhead, keeping their offset, look and fade',
            text and media and (text['startUs'], media['startUs']) == (3_000_000, 4_000_000)
            and text['content']['style'] == hook['content']['style'] and media['content']['transform'] == sticker['content']['transform']
            and media['animIn'] == sticker['animIn'], placed)
    added = [a for a in project(r)['assets'] if a['path'] == arrow['path']]
    r.check("the arrow's file came along under the id its clip names, where it was",
            len(added) == 1 and media and media['content']['assetId'] == added[0]['id'] and Path(arrow['path']).is_file(), added)
    selected = r.s.run('return window.__nuzky.store.getState().selection')
    r.check('the inserted clips are selected', sorted(selected) == sorted(c['id'] for c in placed), selected)
    later = frame(r, 'other-4.5s', 4_500_000)
    r.check('the renderer draws them there as in the first project',
            all(x < 0.002 for x in bands(first, later)) and all(x > 0.01 for x in bands(empty, later)),
            {'from the first project': bands(first, later), 'from the empty frame': bands(empty, later)})
    r.shot('inserted')
    r.key('z', ctrlKey=True)
    r.check("one Ctrl+Z takes the clips and the arrow's file out again",
            wait(lambda: (p := project(r))['tracks'] == before['tracks'] and p['assets'] == before['assets'], 5))

    # Rename in place from the tile's menu.
    r.s.run(TILE_MENU, 'Hook and arrow')
    items = [i['label'] for i in wait(lambda: r.s.run(MENU), 3) or []]
    r.check("the tile's menu offers Put at playhead, Rename and Delete", items == ['Put at playhead', 'Rename', 'Delete'], items)
    r.s.run(PICK, 'Rename')
    name_it(r, 'Arrow hook')
    r.check('Rename keeps the new name', wait(lambda: [e['name'] for e in stored(r)] == ['Arrow hook'], 5), stored(r))

    # Delete, and the toast's Undo.
    r.s.run(TILE_MENU, 'Arrow hook')
    wait(lambda: r.s.run(MENU), 3)
    r.s.run(PICK, 'Delete')
    r.check('Delete takes it out of the list and the file', wait(lambda: stored(r) == [] and r.s.run(TILES) == [], 5), stored(r))
    r.check('a toast offers Undo', wait(lambda: r.s.run(UNDO_TOAST, 'Deleted “Arrow hook”'), 3))
    back = wait(lambda: (s := stored(r)) and s, 5) or []
    r.check('Undo puts it back as it was, with its picture', [e['id'] for e in back] == [element.get('id')]
            and wait(lambda: r.s.run(TILES) == [{'name': 'Arrow hook', 'picture': True}], 5), back)
    r.check('no error toast', not r.errors(), r.errors())

    resize(r, 1024, 640)
    wait(lambda: r.s.run(TILES), 3)
    r.shot('saved-tab-1024')

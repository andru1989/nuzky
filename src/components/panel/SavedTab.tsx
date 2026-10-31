import { Bookmark, Ellipsis } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { cancelNaming, deleteElement, insertElement, loadElements, renameElement, saveNamed, useElements } from "../../lib/elements";
import { formatDuration } from "../../lib/time";
import type { ElementView } from "../../lib/types";
import { Menu, useLockReason } from "../ui";
import { NameField } from "./CaptionsTab";

/** How long an element lasts on the timeline, from its first clip's start to its last clip's end. */
function length(element: ElementView) {
  const starts = element.clips.map((c) => c.clip.startUs);
  const ends = element.clips.map((c) => c.clip.startUs + c.clip.durationUs);
  return Math.max(...ends) - Math.min(...starts);
}

/** What an element holds, for its tile's tooltip. */
function contents(element: ElementView) {
  const kinds = element.clips.map((c) => (c.clip.content.type === "text" ? "text" : c.trackKind === "audio" ? "sound" : "picture"));
  const count = (kind: string) => kinds.filter((k) => k === kind).length;
  return ["text", "picture", "sound"]
    .filter((k) => count(k) > 0)
    .map((k) => `${count(k)} ${k}${count(k) === 1 ? "" : "s"}`)
    .join(", ");
}

/**
 * The user's saved elements: clips kept beside the projects with their media. Clicking one puts it at the
 * playhead; its menu (…, right click, the context menu key) renames (F2) and deletes it (Delete, with Undo).
 */
export function SavedTab() {
  const lock = useLockReason();
  const { list, error, naming } = useElements();
  const [renaming, setRenaming] = useState<{ id: string; error?: string } | null>(null);
  const [savingError, setSavingError] = useState<string | undefined>();
  const [menu, setMenu] = useState<{ element: ElementView; at: { x: number; y: number }; keyboard: boolean } | null>(null);
  const tiles = useRef(new Map<string, HTMLButtonElement>());
  const [focus, setFocus] = useState<string | null>(null);

  useEffect(() => {
    if (list === null) void loadElements();
  }, [list]);
  useEffect(() => {
    if (!focus) return;
    tiles.current.get(focus)?.focus();
    setFocus(null);
  }, [focus, list]);
  useEffect(() => setSavingError(undefined), [naming]);

  const save = async (name: string) => {
    const failed = await saveNamed(name);
    setSavingError(failed ?? undefined);
    if (!failed) setFocus(useElements.getState().list?.[0]?.id ?? null);
  };
  const rename = async (id: string, name: string) => {
    const failed = await renameElement(id, name);
    if (failed) return setRenaming({ id, error: failed });
    setRenaming(null);
    setFocus(id);
  };
  const openMenu = (element: ElementView, at: { x: number; y: number }, keyboard: boolean) => !lock && setMenu({ element, at, keyboard });

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3.5">
      {naming && (
        <div className="flex flex-col gap-1.5">
          <span className="text-[12px] text-muted">
            Save {naming.clipIds.length === 1 ? "the selected clip" : `the ${naming.clipIds.length} selected clips`} as an element
          </span>
          <NameField key={naming.clipIds.join()} label="Element name" maxLength={60} initial={naming.name} error={savingError} onSave={save} onCancel={cancelNaming} />
        </div>
      )}
      {error && <p className="text-[12px] text-danger">{error}</p>}
      {list && list.length === 0 && !naming && (
        <p className="flex gap-1.5 text-[12px] leading-[1.45] text-muted">
          <Bookmark size={14} className="mt-px shrink-0" />
          Right-click clips on the timeline and choose Save as element to keep them here for every project: a text in its style, a sticker, a picture with its fade.
        </p>
      )}
      {list && list.length > 0 && (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(96px,1fr))] gap-2">
          {list.map((element) =>
            renaming?.id === element.id ? (
              <div key={element.id} className="col-span-full">
                <NameField
                  label="Element name"
                  maxLength={60}
                  initial={element.name}
                  error={renaming.error}
                  onSave={(name) => rename(element.id, name)}
                  onCancel={() => {
                    setRenaming(null);
                    setFocus(element.id);
                  }}
                />
              </div>
            ) : (
              <div key={element.id} className="group relative min-w-0" data-element={element.name}>
                <button
                  type="button"
                  ref={(el) => void (el ? tiles.current.set(element.id, el) : tiles.current.delete(element.id))}
                  aria-disabled={!!lock || undefined}
                  title={lock ?? `Put “${element.name}” at the playhead · ${contents(element)}`}
                  onClick={lock ? undefined : () => void insertElement(element)}
                  onContextMenu={(e) => {
                    e.preventDefault();
                    openMenu(element, { x: e.clientX, y: e.clientY }, false);
                  }}
                  onKeyDown={(e) => {
                    if (lock) return;
                    if (e.key === "F2") {
                      e.preventDefault();
                      setRenaming({ id: element.id });
                    } else if (e.key === "Delete" || e.key === "Backspace") {
                      e.preventDefault();
                      e.stopPropagation();
                      void deleteElement(element.id);
                    } else if (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) {
                      e.preventDefault();
                      const r = e.currentTarget.getBoundingClientRect();
                      openMenu(element, { x: r.left, y: r.bottom + 4 }, true);
                    }
                  }}
                  className="flex w-full min-w-0 flex-col gap-1.5 rounded-[10px] text-left aria-disabled:cursor-not-allowed aria-disabled:opacity-40"
                >
                  <span className="relative block aspect-[4/3] w-full overflow-hidden rounded-[10px] border border-white/[.08] bg-bg group-hover:border-white/30">
                    {element.preview ? (
                      <img src={element.preview} alt="" className="absolute inset-0 h-full w-full object-contain" draggable={false} />
                    ) : (
                      <span className="absolute inset-0 flex items-center justify-center text-muted">
                        <Bookmark size={18} />
                      </span>
                    )}
                    <span className="absolute bottom-1 left-1 rounded-md bg-black/60 px-1 text-[10px] tabular-nums text-fg">{formatDuration(length(element))}</span>
                  </span>
                  <span className="truncate text-[11px] text-muted group-hover:text-fg">{element.name}</span>
                </button>
                {!lock && (
                  <button
                    type="button"
                    tabIndex={-1}
                    aria-hidden
                    title="More"
                    onClick={(e) => {
                      const r = e.currentTarget.getBoundingClientRect();
                      openMenu(element, { x: r.left, y: r.bottom + 4 }, false);
                    }}
                    className="absolute top-1 right-1 flex h-5 w-5 items-center justify-center rounded-full bg-black/55 text-fg opacity-0 transition-opacity duration-[120ms] group-hover:opacity-100 hover:bg-black/75"
                  >
                    <Ellipsis size={12} />
                  </button>
                )}
              </div>
            ),
          )}
        </div>
      )}
      {menu && (
        <Menu
          label={`${menu.element.name} element`}
          at={menu.at}
          keyboard={menu.keyboard}
          onClose={(chose) => {
            if (!chose) setFocus(menu.element.id);
            setMenu(null);
          }}
          items={[
            { label: "Put at playhead", run: () => void insertElement(menu.element) },
            { label: "Rename", shortcut: "F2", run: () => setRenaming({ id: menu.element.id }) },
            { label: "Delete", shortcut: "Del", danger: true, run: () => void deleteElement(menu.element.id) },
          ]}
        />
      )}
    </div>
  );
}

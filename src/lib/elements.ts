// The Saved tab's elements: clips kept beside the projects, put into any project at the playhead with their media.
import { create } from "zustand";
import { api, errorText } from "./api";
import { bringMedia, findClip, useEditor } from "./store";
import type { EditCmd, ElementView, Project, SavedElement } from "./types";

export type MediaTabId = "project" | "saved";

interface ElementsState {
  /** The Media tab's part: the project's media or the saved elements. */
  tab: MediaTabId;
  /** Null until the list is read. */
  list: ElementView[] | null;
  error: string | null;
  /** Clips waiting for a name before they are saved, from Save as element. */
  naming: { clipIds: string[]; name: string } | null;
}

export const useElements = create<ElementsState>(() => ({ tab: "project", list: null, error: null, naming: null }));

export async function loadElements() {
  try {
    useElements.setState({ list: await api.savedElements(), error: null });
  } catch (e) {
    useElements.setState({ list: [], error: errorText(e) });
  }
}

/** Runs a change of the list; returns why it failed, or null. */
async function change(run: () => Promise<ElementView[]>): Promise<string | null> {
  try {
    useElements.setState({ list: await run(), error: null });
    return null;
  } catch (e) {
    return errorText(e);
  }
}

/** A name for the clips `ids`: a text's words, a file's name, or how many clips there are. */
function suggestedName(project: Project, ids: string[]): string {
  if (ids.length > 1) return `${ids.length} clips`;
  const clip = findClip(project, ids[0])?.clip;
  if (clip?.content.type === "text") return clip.content.text.replace(/\s+/g, " ").trim().slice(0, 40) || "Text";
  const id = clip?.content.type === "media" ? clip.content.assetId : null;
  const asset = id ? project.assets.find((a) => a.id === id) : undefined;
  return asset ? asset.name.replace(/\.[^.]+$/, "").slice(0, 40) : "Element";
}

/** Save as element: opens Media's Saved part with a field naming the selected clips. */
export function startSavingSelection() {
  const { snap, selection } = useEditor.getState();
  if (!snap || selection.length === 0) return;
  useElements.setState({ tab: "saved", naming: { clipIds: selection, name: suggestedName(snap.project, selection) } });
  useEditor.setState({ panelTab: "media" });
}

/** Saves the clips waiting for a name; returns why it failed, or null. */
export async function saveNamed(name: string): Promise<string | null> {
  const naming = useElements.getState().naming;
  if (!naming) return null;
  const error = await change(() => api.saveElement(name, naming.clipIds));
  if (error) return error;
  useElements.setState({ naming: null });
  useEditor.getState().toast({ kind: "info", text: `Saved “${name.trim()}”` });
  return null;
}

export const cancelNaming = () => useElements.setState({ naming: null });

export const renameElement = (id: string, name: string) => change(() => api.renameElement(id, name));

/** Deletes an element; the toast's Undo puts it back where it was. */
export async function deleteElement(id: string) {
  const { toast } = useEditor.getState();
  try {
    const { element, index, elements } = await api.deleteElement(id);
    useElements.setState({ list: elements });
    toast({ kind: "info", text: `Deleted “${element.name}”`, action: { label: "Undo", run: () => void restore(element, index) } });
  } catch (e) {
    toast({ kind: "error", text: errorText(e) });
  }
}

async function restore(element: SavedElement, index: number) {
  const error = await change(() => api.restoreElement(element, index));
  if (error) useEditor.getState().toast({ kind: "error", text: error });
}

/**
 * Puts an element's clips at the playhead as one undo step, with the media they use; the inserted clips are
 * selected. Clips from a main track go in at the main track's cut nearest the playhead, as a paste does.
 */
export async function insertElement(element: SavedElement) {
  const { timeUs, edit } = useEditor.getState();
  await edit((project): EditCmd[] => {
    const { add, clips } = bringMedia(project, element.clips, element.assets);
    const paste: EditCmd = { type: "pasteClips", clips, atUs: Math.round(timeUs) };
    return add.length > 0 ? [{ type: "addAssets", assets: add }, paste] : [paste];
  });
}

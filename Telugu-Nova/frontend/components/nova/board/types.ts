/**
 * The shared whiteboard's vocabulary. Mirrors backend/src/board.py.
 *
 * Every drawable thing has a TARGET address, used both by Nova ("highlight
 * arr1#3") and by the student's marks ("they circled code1#2"):
 *
 *   arr1        a whole element
 *   arr1#3      cell/item/line 3 (0-based)
 *   tbl1#2.1    table row 2, column 1
 *   tree1#n4    tree node n4
 */

export type Pointer = { name: string; index: number };
export type TreeNode = { id: string; label: string; parent?: string };

export type El =
  | { id: string; kind: 'text'; text: string; label?: string }
  | { id: string; kind: 'code'; lines: string[]; lang?: string; label?: string }
  | { id: string; kind: 'array'; values: string[]; pointers?: Pointer[]; label?: string }
  | {
      id: string;
      kind: 'chain';
      values: string[];
      arrows?: boolean;
      vertical?: boolean;
      label?: string;
    }
  | { id: string; kind: 'tree'; nodes: TreeNode[]; label?: string }
  | { id: string; kind: 'table'; headers?: string[]; rows: string[][]; label?: string }
  | {
      id: string;
      kind: 'diagram';
      layout?: 'flow' | 'cycle' | 'hub' | 'timeline' | 'layers' | 'compare';
      nodes: {
        id: string;
        label: string;
        icon?: string;
        note?: string;
        color?: string;
        group?: string;
      }[];
      edges: { from: string; to: string; label?: string }[];
      label?: string;
    }
  | { id: string; kind: 'list'; items: string[]; label?: string }
  // A generated infographic or clip; the bytes arrive separately (topic nova-media).
  | { id: string; kind: 'media'; media: 'image' | 'video'; caption?: string; label?: string }
  // Nova's improvised handwritten note, pointing back at what it explains.
  | { id: string; kind: 'note'; text: string; target?: string; label?: string };

export type Step = {
  id: string;
  title: string;
  elements: El[];
  say?: string;
  check?: string;
};

export type Lesson = { title: string; steps: Step[] };

/** Agent -> browser, topic "nova-board". */
export type BoardOp =
  | { op: 'planning'; topic: string }
  | { op: 'lesson'; lesson: Lesson }
  | { op: 'reveal'; step: number }
  | { op: 'add'; element: El; after?: string }
  | { op: 'array'; id: string; values?: string[]; pointers?: Pointer[] }
  | { op: 'highlight'; target: string; color?: string }
  | { op: 'arrow'; from: string; to: string; label?: string }
  | { op: 'point'; target: string }
  | { op: 'unmark' }
  | { op: 'clear' }
  | { op: 'board_new'; title?: string }
  | { op: 'board_open' }
  | { op: 'media_fail'; id: string };

/** Browser -> agent, text stream topic "nova-board-student". */
export type StudentMark = {
  type: 'mark';
  id: string;
  /** Which board page the mark was drawn on. */
  board?: string;
  ask: boolean;
  shape: 'circle' | 'underline' | 'scribble';
  targets: { target: string; text: string }[];
  /** JPEG data URL of the marked region, so Nova sees handwriting too. */
  image?: string;
};

export type Rect = { x: number; y: number; w: number; h: number };

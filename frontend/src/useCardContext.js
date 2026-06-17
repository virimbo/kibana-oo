import { useEffect, useRef, useState, useCallback } from "react";

// Hover-intent + pin + keyboard delegation for the SmartContextPanel.
//
// One set of listeners on `document` (event delegation) watches for any element
// carrying `data-smartcard="<id>"`:
//   - hover settles for OPEN_DELAY ms      → open (preview)
//   - leaving for CLOSE_DELAY ms           → close (unless pinned)
//   - keyboard focus of a card            → open immediately (a11y)
//   - click / Enter on a card             → pin open (stays until Esc/close)
//   - Esc                                  → close + unpin, restore focus
//
// `isKnown(id)` lets the caller veto cards that aren't in the registry, so a
// stray data-smartcard never opens an empty panel.
const OPEN_DELAY = 150;
const CLOSE_DELAY = 250;

export default function useCardContext(isKnown) {
  // active: { id, label, status } | null  — the card the panel should describe
  const [active, setActive] = useState(null);
  const [pinned, setPinned] = useState(false);
  const openTimer = useRef(null);
  const closeTimer = useRef(null);
  const lastFocus = useRef(null); // element to restore focus to on Esc
  const pinnedRef = useRef(false);
  pinnedRef.current = pinned;

  const clearTimers = () => {
    if (openTimer.current) clearTimeout(openTimer.current);
    if (closeTimer.current) clearTimeout(closeTimer.current);
    openTimer.current = closeTimer.current = null;
  };

  const close = useCallback(() => {
    clearTimers();
    setPinned(false);
    setActive(null);
  }, []);

  const cardFrom = useCallback(
    (node) => {
      const el = node && node.closest && node.closest("[data-smartcard]");
      if (!el) return null;
      const id = el.getAttribute("data-smartcard");
      if (!id || (isKnown && !isKnown(id))) return null;
      return {
        el,
        id,
        label: el.getAttribute("data-smartlabel") || null,
        status: el.getAttribute("data-smartstatus") || null,
        env: el.getAttribute("data-smartenv") || null,
      };
    },
    [isKnown]
  );

  const openFor = useCallback((card, immediate) => {
    clearTimers();
    const apply = () =>
      setActive((prev) =>
        prev && prev.id === card.id && prev.label === card.label &&
        prev.status === card.status && prev.env === card.env
          ? prev
          : { id: card.id, label: card.label, status: card.status, env: card.env }
      );
    if (immediate) apply();
    else openTimer.current = setTimeout(apply, OPEN_DELAY);
  }, []);

  useEffect(() => {
    const onOver = (e) => {
      if (pinnedRef.current) return;
      const card = cardFrom(e.target);
      if (card) {
        if (closeTimer.current) clearTimeout(closeTimer.current);
        openFor(card, false);
      }
    };
    const onOut = (e) => {
      if (pinnedRef.current) return;
      // Ignore moves that stay within a card or move onto the panel itself.
      const to = e.relatedTarget;
      if (to && to.closest && (to.closest("[data-smartcard]") || to.closest(".scp"))) return;
      if (openTimer.current) clearTimeout(openTimer.current);
      closeTimer.current = setTimeout(() => setActive(null), CLOSE_DELAY);
    };
    const onFocus = (e) => {
      const card = cardFrom(e.target);
      if (card) {
        lastFocus.current = card.el;
        openFor(card, true);
      }
    };
    const onClick = (e) => {
      const card = cardFrom(e.target);
      if (!card) return;
      lastFocus.current = card.el;
      openFor(card, true);
      setPinned((p) => !(p && active && active.id === card.id) ); // toggle pin per card
    };
    const onKey = (e) => {
      if (e.key === "Escape") {
        close();
        if (lastFocus.current && lastFocus.current.focus) lastFocus.current.focus();
      }
    };

    document.addEventListener("mouseover", onOver);
    document.addEventListener("mouseout", onOut);
    document.addEventListener("focusin", onFocus);
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mouseover", onOver);
      document.removeEventListener("mouseout", onOut);
      document.removeEventListener("focusin", onFocus);
      document.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKey);
      clearTimers();
    };
  }, [cardFrom, openFor, close, active]);

  // Keep the panel open while the pointer is over it.
  const holdOpen = useCallback(() => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
  }, []);
  const releaseOpen = useCallback(() => {
    if (pinnedRef.current) return;
    closeTimer.current = setTimeout(() => setActive(null), CLOSE_DELAY);
  }, []);

  return { active, pinned, close, holdOpen, releaseOpen };
}

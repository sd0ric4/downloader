import { useState, useEffect } from 'react';

export function useAuthNavigation(elements: string[]) {
  const [focusedElementId, setFocusedElementId] = useState<string>(elements[0]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const currentIndex = elements.indexOf(focusedElementId);
      let nextIndex: number;

      switch (e.key) {
        case 'ArrowUp':
          e.preventDefault();
          nextIndex = currentIndex > 0 ? currentIndex - 1 : elements.length - 1;
          break;
        case 'ArrowDown':
          e.preventDefault();
          nextIndex = currentIndex < elements.length - 1 ? currentIndex + 1 : 0;
          break;
        default:
          return;
      }

      const nextElement = document.getElementById(elements[nextIndex]);
      nextElement?.focus();
      setFocusedElementId(elements[nextIndex]);
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [focusedElementId, elements]);

  const handleFocus = (elementId: string) => setFocusedElementId(elementId);
  const getFocusClass = (elementId: string) =>
    focusedElementId === elementId ? 'ring-2 ring-blue-500' : '';

  return { focusedElementId, handleFocus, getFocusClass };
}

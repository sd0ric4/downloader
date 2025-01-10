import { useCallback } from 'react';
import { useNavigate } from 'react-router';
import { useContext } from 'react';
import { TransitionContext } from '../context/TransitionProvider';

export function useRouteTransition() {
  const navigate = useNavigate();
  const { startTransition, endTransition } = useContext(TransitionContext);

  const navigateWithTransition = useCallback(
    (to: string) => {
      startTransition();
      setTimeout(() => {
        navigate(to);
        requestAnimationFrame(() => {
          endTransition();
        });
      }, 300);
    },
    [navigate, startTransition, endTransition]
  );

  return navigateWithTransition;
}

import { createContext, useState, type ReactNode } from 'react';
import '../styles/transition.css';

export const TransitionContext = createContext({
  isTransitioning: false,
  startTransition: () => {},
  endTransition: () => {},
});

export function TransitionProvider({ children }: { children: ReactNode }) {
  const [isTransitioning, setIsTransitioning] = useState(false);
  const [pageState, setPageState] = useState<'active' | 'leave' | 'enter'>(
    'active'
  );

  return (
    <TransitionContext.Provider
      value={{
        isTransitioning,
        startTransition: () => {
          setIsTransitioning(true);
          setPageState('leave');
        },
        endTransition: () => {
          setPageState('enter');
          requestAnimationFrame(() => {
            setPageState('active');
            setIsTransitioning(false);
          });
        },
      }}
    >
      <div className={`page-container page-${pageState}`}>
        <div className='page-outer'>
          <div className='page-inner'>{children}</div>
        </div>
      </div>
    </TransitionContext.Provider>
  );
}

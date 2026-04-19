import '@testing-library/jest-dom/vitest'
import { beforeEach, afterEach, vi } from 'vitest'

// Global test setup
beforeEach(() => {
  // Reset any mocks or global state here
});

afterEach(() => {
  // Clean up after each test
});

// Mock global objects if needed
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(), // deprecated
    removeListener: vi.fn(), // deprecated
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

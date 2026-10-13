import '@testing-library/jest-dom/vitest'

// favorites live in localStorage: every test starts as a first-time visitor
beforeEach(() => window.localStorage.clear())

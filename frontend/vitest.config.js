import { defineConfig } from 'vitest/config'

// Vitest 3 runs on its own Vite 7 (esbuild), where @vitejs/plugin-react 6 (Vite 8 / oxc)
// does not set up JSX, so tell esbuild to use the automatic React runtime for .jsx files.
export default defineConfig({
  esbuild: { jsx: 'automatic' },
})

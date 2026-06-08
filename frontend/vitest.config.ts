import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setupTests.ts'],
    passWithNoTests: true,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'json-summary'],
      reportsDirectory: './coverage',
      exclude: [
        'dist/**',
        'node_modules/**',
        '**/*.d.ts',
        '**/vite.config.ts',
        '**/vitest.config.ts',
        'src/main.tsx',
      ],
    },
  },
})

module.exports = {
  env: { browser: true, es2022: true, node: true },
  ignorePatterns: ['dist', 'node_modules'],
  extends: ['eslint:recommended', 'plugin:react/recommended', 'plugin:react-hooks/recommended'],
  plugins: ['react', 'react-hooks'],
  parserOptions: { ecmaVersion: 'latest', sourceType: 'module', ecmaFeatures: { jsx: true } },
  settings: { react: { version: 'detect' } },
  globals: { describe: 'readonly', it: 'readonly', expect: 'readonly' },
  rules: {
    'no-unused-vars': 'off',
    'no-undef': 'error',
    'react/prop-types': 'off',
    'react/react-in-jsx-scope': 'off',
    'react-hooks/exhaustive-deps': 'warn',
  },
};

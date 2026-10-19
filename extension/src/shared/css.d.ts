// Vite returns processed CSS as a string for `?inline` imports — used to inject
// the shared proofing-desk tokens into the on-page Shadow-DOM proof layer (T15).
declare module '*.css?inline' {
  const css: string
  export default css
}

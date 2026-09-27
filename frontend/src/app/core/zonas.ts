/**
 * Las cuatro zonas de exigencia, con su color y su orden.
 *
 * Los nombres los pone el backend (salen del k-means del notebook); aquí solo
 * se decide cómo se pintan y cuál pesa más al contar la carrera. Los colores
 * son los del notebook y no cambian con el tema.
 */
export const COLOR_ZONA: Record<string, string> = {
  Recuperación: '#27ae60',
  Crucero: '#3498db',
  'Exigencia alta': '#f39c12',
  'Exigencia crítica': '#e74c3c',
};

/** Para lo que no esté en la tabla, un gris neutro en vez de un hueco. */
export const COLOR_SIN_ZONA = '#95a5a6';

/** De menos a más exigente. */
export const SEVERIDAD_ZONA: Record<string, number> = {
  Recuperación: 0,
  Crucero: 1,
  'Exigencia alta': 2,
  'Exigencia crítica': 3,
};

export function colorDe(zona: string): string {
  return COLOR_ZONA[zona] ?? COLOR_SIN_ZONA;
}

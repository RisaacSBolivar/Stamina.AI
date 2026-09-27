/**
 * Producción: la interfaz vive en Vercel y la API en Render, en otro dominio.
 *
 * El navegador llama a la API directamente (con CORS) y no a través de Vercel:
 * así no le afectan ni el tope de 4.5 MB por petición ni los 120 s con los que
 * Vercel corta una petición reenviada a otro servidor. Si el servicio de Render
 * cambia de nombre, esta es la única línea que hay que tocar.
 */
export const environment = {
  apiUrl: 'https://stamina-ai-api.onrender.com/api/v1',
};

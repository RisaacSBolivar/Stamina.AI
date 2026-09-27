/**
 * Modo claro u oscuro.
 *
 * El tema se aplica poniendo `data-tema` en el `<html>`, y todo lo demás sale
 * solo: los colores son tokens CSS y la hoja de estilos los redefine para el
 * modo oscuro. Ningún componente sabe en qué tema está, salvo la gráfica, que
 * pinta en un canvas y no puede leer variables CSS.
 *
 * Se guarda en `localStorage` y no en `sessionStorage`, al revés que el nombre:
 * esto no es un dato de la sesión sino una preferencia de cómo se ve la
 * aplicación, y lo normal es que sobreviva a cerrar la pestaña.
 */
import { Injectable, effect, signal } from '@angular/core';

export type Tema = 'claro' | 'oscuro';

const CLAVE = 'stamina.tema';

function leerGuardado(): Tema | null {
  try {
    const valor = localStorage.getItem(CLAVE);
    return valor === 'claro' || valor === 'oscuro' ? valor : null;
  } catch {
    // Navegación privada o almacenamiento bloqueado: se usa el del sistema.
    return null;
  }
}

/** Lo que el sistema operativo ya tiene elegido. Es el mejor punto de partida. */
function delSistema(): Tema {
  try {
    return matchMedia('(prefers-color-scheme: dark)').matches ? 'oscuro' : 'claro';
  } catch {
    return 'claro';
  }
}

@Injectable({ providedIn: 'root' })
export class TemaService {
  readonly tema = signal<Tema>(leerGuardado() ?? delSistema());

  constructor() {
    // Aplicar y recordar van juntos: no hay forma de cambiar el tema sin que se
    // note ni de que se note sin quedar recordado.
    effect(() => {
      const tema = this.tema();
      document.documentElement.dataset['tema'] = tema;
      try {
        localStorage.setItem(CLAVE, tema);
      } catch {
        // Sin almacenamiento el tema vive lo que dure la página, y basta.
      }
    });
  }

  alternar(): void {
    this.tema.set(this.tema() === 'claro' ? 'oscuro' : 'claro');
  }
}

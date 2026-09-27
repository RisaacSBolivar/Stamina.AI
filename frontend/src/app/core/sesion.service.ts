/**
 * Quién está usando la aplicación durante esta sesión.
 *
 * El nombre sirve para saludar y para nada más: no viaja al backend, no se
 * cruza con el historial ni con las credenciales de Garmin, y no hay cuentas ni
 * base de datos detrás. Es opcional — sin él la aplicación funciona entera y
 * solo se pierde el saludo de la cabecera.
 *
 * Se guarda en `sessionStorage` y no en `localStorage` a propósito: vive en la
 * pestaña y se borra al cerrarla, que es exactamente lo que dura el resto del
 * estado (el historial y las estrategias están en memoria con TTL, sin
 * persistencia).
 */
import { Injectable, signal } from '@angular/core';

/** Cabe en la cabecera sin empujar la marca. Se recorta, no se rechaza. */
const LARGO_MAXIMO = 24;

const CLAVE = 'stamina.nombre';

/**
 * En navegación privada o con el almacenamiento bloqueado, `sessionStorage`
 * lanza al tocarlo. No es motivo para romper la aplicación: se sigue sin nombre.
 */
function leerGuardado(): string | null {
  try {
    return sessionStorage.getItem(CLAVE) || null;
  } catch {
    return null;
  }
}

function guardar(nombre: string | null): void {
  try {
    if (nombre) sessionStorage.setItem(CLAVE, nombre);
    else sessionStorage.removeItem(CLAVE);
  } catch {
    // Sin almacenamiento el nombre vive solo en memoria, y basta.
  }
}

@Injectable({ providedIn: 'root' })
export class SesionService {
  /** El nombre con el que saludar, o null si nadie se ha presentado. */
  readonly nombre = signal<string | null>(leerGuardado());

  /** Recordar el nombre de esta sesión. Vacío o solo espacios cuenta como no dar ninguno. */
  presentarse(nombre: string): void {
    const limpio = nombre.trim().slice(0, LARGO_MAXIMO) || null;
    this.nombre.set(limpio);
    guardar(limpio);
  }

  /**
   * Al salir, el nombre se va con el resto.
   *
   * Si sobreviviera, la siguiente persona que abriera la pestaña seria recibida
   * con el saludo de la anterior.
   */
  olvidar(): void {
    this.nombre.set(null);
    guardar(null);
  }
}

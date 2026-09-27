/**
 * Confirmaciones dentro de la aplicacion, no del navegador.
 *
 * El `confirm()` nativo rotula el dialogo con el origen de la pagina
 * («localhost:4200 dice…») y eso no se puede cambiar desde JavaScript: es la
 * defensa del navegador para que un sitio no pueda hacerse pasar por otro en un
 * dialogo del sistema. La unica forma de que la confirmacion se vea de la marca
 * es no usar el dialogo del sistema.
 *
 * Lo que no cambia es la garantia: ninguna operacion contra la cuenta de Garmin
 * ocurre sin que la persona la confirme a proposito.
 */
import { Injectable, signal } from '@angular/core';

export interface PeticionConfirmacion {
  titulo: string;
  mensaje: string;
  /** Segunda linea, para la letra pequena de lo que va a pasar. */
  detalle?: string;
  textoConfirmar?: string;
  textoCancelar?: string;
}

@Injectable({ providedIn: 'root' })
export class ConfirmacionService {
  /** La peticion abierta, o `null`. La pinta `<app-dialogo-confirmar>`. */
  readonly peticion = signal<PeticionConfirmacion | null>(null);

  private resolver: ((aceptado: boolean) => void) | null = null;

  /**
   * Pide confirmacion y espera. Sustituye a `confirm()` con la misma forma:
   * `if (!(await confirmacion.pedir(...))) return;`
   */
  pedir(peticion: PeticionConfirmacion): Promise<boolean> {
    // Si quedara una abierta, se da por cancelada antes de sustituirla.
    this.responder(false);
    this.peticion.set(peticion);
    return new Promise<boolean>((resolve) => {
      this.resolver = resolve;
    });
  }

  /** Cierra la peticion abierta. Cancelar es siempre lo seguro por defecto. */
  responder(aceptado: boolean): void {
    const resolver = this.resolver;
    this.resolver = null;
    this.peticion.set(null);
    resolver?.(aceptado);
  }
}

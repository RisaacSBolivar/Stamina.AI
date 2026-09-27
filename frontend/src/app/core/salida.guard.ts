/**
 * Confirmar antes de volver a la portada, y borrar al salir.
 *
 * Es una guarda de ruta y no el manejador de un botón porque la flecha atrás
 * del navegador también saca de aquí, y por ahí no pasa ningún `click` nuestro.
 * Poniéndolo en la ruta, salir por el botón y salir con la flecha atrás hacen
 * exactamente lo mismo: una sola implementación y ninguna puerta trasera.
 */
import { inject } from '@angular/core';
import type { CanDeactivateFn } from '@angular/router';

import { ConfirmacionService } from './confirmacion.service';
import { EstadoService } from './estado.service';
import { SesionService } from './sesion.service';

/** Volver aquí es salir; cualquier otro destino es moverse por dentro. */
const RUTA_PORTADA = '/bienvenida';

export const puedeSalir: CanDeactivateFn<unknown> = (_componente, _ruta, _actual, siguiente) => {
  // Ir de la estrategia al detalle y volver no es salir, y preguntarlo cada vez
  // convertiria el aviso en ruido que se acepta sin leer.
  if (!siguiente.url.startsWith(RUTA_PORTADA)) return true;

  const estado = inject(EstadoService);
  const sesion = inject(SesionService);
  const confirmacion = inject(ConfirmacionService);

  // Sin nada cargado no hay nada que perder. Avisar de que se van a borrar
  // datos que no existen seria decir algo falso.
  if (!estado.hayAlgoQuePerder()) {
    sesion.olvidar();
    return true;
  }

  return confirmacion
    .pedir({
      titulo: '¿Seguro que quieres salir?',
      mensaje:
        'Se borra todo lo de esta sesión: tu historial, la ruta, la estrategia y tu nombre. ' +
        'Tendrías que volver a subir los archivos.',
      detalle:
        'Nada de esto se guardó en el servidor: vivía en esta pestaña. Si tenías Garmin ' +
        'conectado, también se cierra esa sesión.',
      textoConfirmar: 'Salir y borrar',
      textoCancelar: 'Seguir aquí',
    })
    .then(async (seguro) => {
      if (!seguro) return false;
      await estado.olvidar();
      sesion.olvidar();
      return true;
    });
};

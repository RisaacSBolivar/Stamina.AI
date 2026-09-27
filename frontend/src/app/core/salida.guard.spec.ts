import { provideZonelessChangeDetection } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import type { RouterStateSnapshot } from '@angular/router';
import { vi } from 'vitest';

import { ApiService } from './api.service';
import { ConfirmacionService } from './confirmacion.service';
import { EstadoService } from './estado.service';
import { puedeSalir } from './salida.guard';
import { SesionService } from './sesion.service';

/** Al guardia solo le importa a dónde se va; el resto del snapshot no lo mira. */
const hacia = (url: string) => ({ url }) as RouterStateSnapshot;
const NADA = undefined as never;

const olvidarEnElServidor = vi.fn(() => Promise.resolve());

describe('puedeSalir', () => {
  beforeEach(async () => {
    sessionStorage.clear();
    olvidarEnElServidor.mockClear();

    await TestBed.configureTestingModule({
      providers: [
        provideZonelessChangeDetection(),
        // Doble en vez de HttpClient de prueba: aquí se comprueba el guardia, y
        // que la llamada salga con lo que debe.
        { provide: ApiService, useValue: { olvidar: olvidarEnElServidor } },
      ],
    }).compileComponents();
  });

  const correr = (url: string) =>
    TestBed.runInInjectionContext(() => puedeSalir(null, NADA, NADA, hacia(url)));

  it('no pregunta al pasar al detalle, porque eso no es salir', async () => {
    TestBed.inject(EstadoService).garminAutenticada.set(true);
    const pedir = vi.spyOn(TestBed.inject(ConfirmacionService), 'pedir');

    expect(await correr('/detalle')).toBe(true);
    expect(pedir).not.toHaveBeenCalled();
  });

  it('no pregunta si no hay nada que perder', async () => {
    const pedir = vi.spyOn(TestBed.inject(ConfirmacionService), 'pedir');

    // Avisar de que se van a borrar datos que no existen seria decir algo falso.
    expect(await correr('/bienvenida')).toBe(true);
    expect(pedir).not.toHaveBeenCalled();
  });

  it('bloquea la salida si se cancela, y no toca nada', async () => {
    const estado = TestBed.inject(EstadoService);
    estado.garminAutenticada.set(true);
    estado.sesionGarminId.set('ses-1');

    const veredicto = correr('/bienvenida') as Promise<boolean>;
    TestBed.inject(ConfirmacionService).responder(false);

    expect(await veredicto).toBe(false);
    expect(estado.sesionGarminId()).toBe('ses-1');
    expect(olvidarEnElServidor).not.toHaveBeenCalled();
  });

  it('al confirmar cierra la sesión de Garmin y deja todo a cero', async () => {
    const estado = TestBed.inject(EstadoService);
    const sesion = TestBed.inject(SesionService);
    estado.garminAutenticada.set(true);
    estado.sesionGarminId.set('ses-1');
    estado.tiempoObjetivoH.set(3.2);
    sesion.presentarse('Isaac');

    const veredicto = correr('/bienvenida') as Promise<boolean>;
    TestBed.inject(ConfirmacionService).responder(true);

    expect(await veredicto).toBe(true);

    // El historial nunca estuvo en el servidor; lo único que hay que soltar
    // allí es la sesión de Garmin, que sostiene una cuenta real.
    expect(olvidarEnElServidor).toHaveBeenCalledWith({ sesion_garmin_id: 'ses-1' });

    expect(estado.sesionGarminId()).toBeNull();
    expect(estado.garminAutenticada()).toBe(false);
    expect(estado.tiempoObjetivoH()).toBe(4);
    expect(sesion.nombre()).toBeNull();
  });
});

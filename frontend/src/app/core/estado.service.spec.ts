import { provideZonelessChangeDetection } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { ApiService, type Capacidad, type Salud } from './api.service';
import { EstadoService, type HistorialLocal } from './estado.service';

/** Lo mínimo que mira el aviso. El resto del contrato no interviene. */
const capacidadPersonalizada = {
  modelo: 'Base física',
  personalizada: true,
  motivo: null,
  horas: 12.03,
  km_objetivo: 42.2,
  habilidad_esperada: 0.221,
  nivel_capacidad: 1,
  regimen_fiable: true,
  distancia_extrapolada: false,
  validado_en_km: [10, 16],
  siguiente_franja: null,
  franjas: [],
} as unknown as Capacidad;

const capacidadCorta = {
  ...capacidadPersonalizada,
  personalizada: false,
  motivo: 'sin_evidencia_en_esta_franja',
  horas: 6.14,
  siguiente_franja: { desde_horas: 10.0, modelo: 'Base física', habilidad: 0.221, horas_faltantes: 3.86 },
} as unknown as Capacidad;

const historial = { procesado: {}, resumen: {} } as unknown as HistorialLocal;

describe('EstadoService', () => {
  let estado: EstadoService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideZonelessChangeDetection(),
        { provide: ApiService, useValue: {} },
      ],
    });
    estado = TestBed.inject(EstadoService);
  });

  it('no deja calcular con una ruta pero sin historial', () => {
    estado.gpx.set(new File([''], 'ruta.gpx'));

    // Ya no hay modelo del autor al que recurrir: sin historial no hay estrategia.
    expect(estado.puedeCalcular()).toBe(false);
  });

  it('deja calcular con historial y ruta', () => {
    estado.gpx.set(new File([''], 'ruta.gpx'));
    estado.historial.set(historial);

    expect(estado.puedeCalcular()).toBe(true);
  });

  it('personalizada: dice cuánto error quita, en una frase corta', () => {
    estado.capacidad.set(capacidadPersonalizada);
    const aviso = estado.disclaimer();

    expect(aviso?.titulo).toBe('Estrategia personalizada');
    expect(aviso?.cuerpo).toContain('Reduce alrededor de un 22% el error');
  });

  it('sin evidencia: ritmo constante y cuánto falta, sin inventar el umbral', () => {
    estado.capacidad.set(capacidadCorta);
    const aviso = estado.disclaimer();

    expect(aviso?.titulo).toBe('Ritmo constante: todavía no hay evidencia para personalizar');
    // Las 3.9 h salen de la capacidad que dio la API, no de un número escrito aquí.
    expect(aviso?.cuerpo).toContain('te faltan 3.9 h');
  });

  it('Garmin solo aparece si el despliegue lo tiene encendido', () => {
    expect(estado.garminDisponible()).toBe(false);

    estado.salud.set({ garmin_habilitado: true, reglas: { cargadas: true } } as unknown as Salud);
    expect(estado.garminDisponible()).toBe(true);

    estado.salud.set({ garmin_habilitado: false, reglas: { cargadas: true } } as unknown as Salud);
    expect(estado.garminDisponible()).toBe(false);
  });

  it('salir deja la aplicación como recién abierta', () => {
    estado.historial.set(historial);
    estado.capacidad.set(capacidadPersonalizada);
    estado.tiempoObjetivoH.set(3.2);
    estado.reiniciar();

    expect(estado.historial()).toBeNull();
    expect(estado.capacidad()).toBeNull();
    expect(estado.tiempoObjetivoH()).toBe(4);
  });
});

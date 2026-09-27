import { provideZonelessChangeDetection } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { TemaService } from './tema.service';

describe('TemaService', () => {
  beforeEach(() => {
    localStorage.removeItem('stamina.tema');
    delete document.documentElement.dataset['tema'];
    TestBed.configureTestingModule({ providers: [provideZonelessChangeDetection()] });
  });

  it('arranca en claro cuando no hay nada guardado ni preferencia del sistema', () => {
    // jsdom no implementa `matchMedia`, que es justo el caso que el servicio
    // tiene que sobrevivir sin romperse.
    expect(TestBed.inject(TemaService).tema()).toBe('claro');
  });

  it('respeta lo que se eligió la última vez', () => {
    localStorage.setItem('stamina.tema', 'oscuro');

    expect(TestBed.inject(TemaService).tema()).toBe('oscuro');
  });

  it('al alternar lo aplica al documento y lo recuerda', () => {
    const tema = TestBed.inject(TemaService);
    tema.alternar();
    // El efecto que aplica y guarda el tema corre con la deteccion de cambios.
    TestBed.tick();

    expect(tema.tema()).toBe('oscuro');
    expect(document.documentElement.dataset['tema']).toBe('oscuro');
    expect(localStorage.getItem('stamina.tema')).toBe('oscuro');
  });

  it('ignora un valor corrupto en el almacenamiento', () => {
    localStorage.setItem('stamina.tema', 'fucsia');

    expect(TestBed.inject(TemaService).tema()).toBe('claro');
  });
});

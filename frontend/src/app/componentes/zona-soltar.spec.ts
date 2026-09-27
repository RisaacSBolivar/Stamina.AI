import { provideZonelessChangeDetection } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { vi } from 'vitest';

import { ZonaSoltar } from './zona-soltar';

describe('ZonaSoltar', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ZonaSoltar],
      providers: [provideZonelessChangeDetection()],
    }).compileComponents();
  });

  function montar(esperando: string | null): ComponentFixture<ZonaSoltar> {
    const fixture = TestBed.createComponent(ZonaSoltar);
    fixture.componentRef.setInput('etiqueta', 'Arrastra tus archivos .FIT');
    fixture.componentRef.setInput('ayuda', 'o haz clic para elegirlos');
    fixture.componentRef.setInput('esperando', esperando);
    fixture.detectChanges();
    return fixture;
  }

  const zonaDe = (fixture: ComponentFixture<ZonaSoltar>): HTMLElement =>
    fixture.nativeElement.querySelector('.soltar') as HTMLElement;

  const entradaDe = (fixture: ComponentFixture<ZonaSoltar>): HTMLInputElement =>
    fixture.nativeElement.querySelector('input[type=file]') as HTMLInputElement;

  it('abre el selector de archivos cuando no espera a nada', () => {
    const fixture = montar(null);
    const abrir = vi.spyOn(entradaDe(fixture), 'click');

    zonaDe(fixture).click();

    expect(abrir).toHaveBeenCalled();
    expect(zonaDe(fixture).getAttribute('aria-disabled')).toBe('false');
    expect(zonaDe(fixture).getAttribute('tabindex')).toBe('0');
    expect(zonaDe(fixture).textContent).toContain('o haz clic para elegirlos');
  });

  it('se apaga mientras el historial está llegando, y dice por qué', () => {
    const zona = zonaDe(montar('Descargando tu historial de Garmin…'));

    // Apagarla sin decir por qué sería el mismo defecto que un botón muerto.
    expect(zona.classList.contains('soltar--apagada')).toBe(true);
    expect(zona.getAttribute('aria-disabled')).toBe('true');
    expect(zona.textContent).toContain('Descargando tu historial de Garmin');
  });

  it('no abre el selector mientras espera, ni con teclado', () => {
    const fixture = montar('Procesando tu historial…');
    const abrir = vi.spyOn(entradaDe(fixture), 'click');

    // El ratón lo corta el CSS (`pointer-events: none`), que aquí no se aplica;
    // lo que se comprueba es la guarda del componente, que es la que vale para
    // el teclado y para un foco puesto a mano.
    zonaDe(fixture).click();
    zonaDe(fixture).dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

    expect(abrir).not.toHaveBeenCalled();
    expect(zonaDe(fixture).getAttribute('tabindex')).toBe('-1');
  });
});

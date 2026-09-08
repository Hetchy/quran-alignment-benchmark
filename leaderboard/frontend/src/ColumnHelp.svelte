<script lang="ts">
  import { onMount } from 'svelte';
  export let name: string;
  export let text: string;
  export let id: string;
  let open = false;
  let trigger: HTMLButtonElement;
  let wrapper: HTMLSpanElement;
  let left = 0, top = 0;
  function show() {
    const rect = trigger.getBoundingClientRect();
    left = Math.max(12, Math.min(rect.left - 120, window.innerWidth - 292));
    top = rect.bottom + 8;
    open = true;
  }
  onMount(() => {
    const close = () => { open = false; };
    const outside = (event: PointerEvent) => { if (!wrapper.contains(event.target as Node)) close(); };
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') close(); };
    window.addEventListener('scroll', close, true);
    window.addEventListener('resize', close);
    window.addEventListener('pointerdown', outside);
    window.addEventListener('keydown', escape);
    return () => {
      window.removeEventListener('scroll', close, true);
      window.removeEventListener('resize', close);
      window.removeEventListener('pointerdown', outside);
      window.removeEventListener('keydown', escape);
    };
  });
</script>

<span bind:this={wrapper} class="column-help" role="group" aria-label={`${name} help`} onpointerleave={() => open = false}>
  <button bind:this={trigger} type="button" class="help-trigger" aria-label={`About ${name}`} aria-describedby={open ? id : undefined} onpointerenter={show} onfocus={show} onblur={() => open = false} onclick={show}><span class="help-icon" aria-hidden="true">?</span></button>
  {#if open}<span {id} role="tooltip" class="column-tooltip" style:left={`${left}px`} style:top={`${top}px`}>{text}</span>{/if}
</span>

<style>
  .column-help {display:inline-flex;vertical-align:middle;margin-left:4px;}
  button.help-trigger {display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;padding:0;border:0;border-radius:50%;color:var(--muted);background:transparent;font-size:11px;cursor:help;}
  .help-icon {display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;box-sizing:border-box;border:1px solid currentColor;border-radius:50%;line-height:1;}
  button.help-trigger:hover, button.help-trigger:focus-visible {color:var(--primary);background:var(--tint);}
  .column-tooltip {position:fixed;z-index:40;width:280px;max-width:calc(100vw - 24px);padding:12px 14px;border:1px solid var(--border);border-radius:7px;background:var(--bg);color:var(--ink);box-shadow:0 4px 18px #0002;white-space:normal;text-align:left;font-size:12px;font-weight:400;line-height:1.55;}
</style>

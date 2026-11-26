/**
 * THE CHRONO-VAULT AEGIS — 60 FPS Dual-Theme Interactive Kinetic Canvas
 * Adapts automatically between Obsidian Dark Mode and Editorial Ivory Light Mode.
 * Zero External Dependencies (Pure HTML5 Canvas 2D Engine).
 * Engineered by Neal Frazier Tech (@1nc0gn30) • NullAI Platform.
 */

(function () {
  'use strict';

  let canvas = null;
  let ctx = null;
  let width = 0;
  let height = 0;
  let dpr = 1;
  let animId = null;

  let breakerState = 'CLOSED';
  let mouse = { x: 0, y: 0, targetX: 0, targetY: 0, isHovered: false };
  let pulseWave = 0;
  let time = 0;

  const PARTICLES_COUNT = 52;
  const particles = [];

  function isLightMode() {
    return document.documentElement.getAttribute('data-theme') === 'light';
  }

  class TokenParticle {
    constructor() {
      this.reset(true);
    }

    reset(initial = false) {
      const angle = Math.random() * Math.PI * 2;
      const dist = initial ? Math.random() * 240 + 55 : Math.random() * 75 + 220;
      this.x = Math.cos(angle) * dist;
      this.y = Math.sin(angle) * dist;
      this.targetDist = Math.random() * 85 + 30;
      this.angle = angle;
      this.angularSpeed = (Math.random() - 0.5) * 0.032;
      this.size = Math.random() * 2.1 + 1.2;
      this.alpha = Math.random() * 0.65 + 0.3;
      this.type = Math.random() > 0.35 ? 'emerald' : (Math.random() > 0.5 ? 'gold' : 'ruby');
    }

    update() {
      this.angle += this.angularSpeed;
      const currentDist = Math.sqrt(this.x * this.x + this.y * this.y);
      if (currentDist > this.targetDist) {
        this.x *= 0.992;
        this.y *= 0.992;
      } else {
        this.x = Math.cos(this.angle) * currentDist;
        this.y = Math.sin(this.angle) * currentDist;
      }

      if (mouse.isHovered) {
        const dx = this.x - mouse.x;
        const dy = this.y - mouse.y;
        const d = Math.sqrt(dx * dx + dy * dy);
        if (d < 80 && d > 0) {
          const force = (80 - d) / 80;
          this.x += (dx / d) * force * 4;
          this.y += (dy / d) * force * 4;
        }
      }

      if (currentDist < 20 || currentDist > 330) {
        this.reset();
      }
    }

    draw(context, centerX, centerY, light) {
      const px = centerX + this.x;
      const py = centerY + this.y;

      let col = light ? '#047857' : '#10B981';
      if (breakerState === 'TRIPPED') {
        col = Math.random() > 0.3 ? (light ? '#B91C1C' : '#EF4444') : (light ? '#B45309' : '#F59E0B');
      } else if (breakerState === 'WARN') {
        col = Math.random() > 0.5 ? (light ? '#B45309' : '#F59E0B') : (light ? '#047857' : '#10B981');
      } else if (this.type === 'gold') {
        col = light ? '#9A7218' : '#D4AF37';
      } else if (this.type === 'ruby') {
        col = light ? '#B91C1C' : '#EF4444';
      }

      context.save();
      context.beginPath();
      context.arc(px, py, this.size, 0, Math.PI * 2);
      context.fillStyle = col;
      context.shadowColor = col;
      context.shadowBlur = light ? 4 : 8;
      context.globalAlpha = this.alpha;
      context.fill();
      context.restore();
    }
  }

  function init() {
    canvas = document.getElementById('chronoVaultCanvas');
    if (!canvas) return;
    ctx = canvas.getContext('2d');
    resize();
    window.addEventListener('resize', resize);

    canvas.addEventListener('mousemove', onMouseMove);
    canvas.addEventListener('mouseenter', () => { mouse.isHovered = true; });
    canvas.addEventListener('mouseleave', () => {
      mouse.isHovered = false;
      mouse.targetX = 0;
      mouse.targetY = 0;
    });
    canvas.addEventListener('click', triggerPulse);
    canvas.addEventListener('touchmove', onTouchMove, { passive: true });
    canvas.addEventListener('touchend', () => {
      mouse.isHovered = false;
      mouse.targetX = 0;
      mouse.targetY = 0;
    });

    particles.length = 0;
    for (let i = 0; i < PARTICLES_COUNT; i++) {
      particles.push(new TokenParticle());
    }

    if (animId) cancelAnimationFrame(animId);
    animate();
  }

  function resize() {
    if (!canvas) return;
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    const rect = canvas.getBoundingClientRect();
    width = rect.width || canvas.parentElement.clientWidth || 600;
    height = rect.height || 280;

    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.scale(dpr, dpr);
  }

  function onMouseMove(e) {
    const rect = canvas.getBoundingClientRect();
    mouse.targetX = e.clientX - rect.left - rect.width / 2;
    mouse.targetY = e.clientY - rect.top - rect.height / 2;
    mouse.isHovered = true;
  }

  function onTouchMove(e) {
    if (!e.touches || e.touches.length === 0) return;
    const rect = canvas.getBoundingClientRect();
    mouse.targetX = e.touches[0].clientX - rect.left - rect.width / 2;
    mouse.targetY = e.touches[0].clientY - rect.top - rect.height / 2;
    mouse.isHovered = true;
  }

  function triggerPulse() {
    pulseWave = 1.0;
  }

  function drawShieldPath(context, cx, cy, scale) {
    const w = 64 * scale;
    const h = 84 * scale;
    const topChamfer = 13 * scale;
    const waist = 26 * scale;

    context.beginPath();
    context.moveTo(cx - w + topChamfer, cy - h);
    context.lineTo(cx + w - topChamfer, cy - h);
    context.lineTo(cx + w, cy - h + topChamfer);
    context.quadraticCurveTo(cx + w + 4 * scale, cy - waist, cx + w * 0.78, cy + 10 * scale);
    context.quadraticCurveTo(cx + w * 0.5, cy + h * 0.72, cx, cy + h);
    context.quadraticCurveTo(cx - w * 0.5, cy + h * 0.72, cx - w * 0.78, cy + 10 * scale);
    context.quadraticCurveTo(cx - w - 4 * scale, cy - waist, cx - w, cy - h + topChamfer);
    context.closePath();
  }

  function drawCircuitCoil(context, cx, cy, rx, ry, tiltAngle, phase, color, glowColor, lineWidth, isTripped) {
    context.save();
    context.translate(cx, cy);
    context.rotate(tiltAngle);

    context.beginPath();
    context.ellipse(0, 0, rx, ry, 0, 0, Math.PI * 2);
    context.strokeStyle = color;
    context.lineWidth = lineWidth;
    context.shadowColor = glowColor;
    context.shadowBlur = isTripped ? 14 : 6;
    context.stroke();

    const nodeAngle = phase % (Math.PI * 2);
    const nx = Math.cos(nodeAngle) * rx;
    const ny = Math.sin(nodeAngle) * ry;

    context.beginPath();
    context.arc(nx, ny, isTripped ? 4.2 : 3.2, 0, Math.PI * 2);
    context.fillStyle = isLightMode() ? glowColor : '#FFFFFF';
    context.shadowColor = glowColor;
    context.shadowBlur = 10;
    context.fill();

    for (let i = 1; i <= 3; i++) {
      const trailAngle = nodeAngle - i * 0.15;
      context.beginPath();
      context.arc(Math.cos(trailAngle) * rx, Math.sin(trailAngle) * ry, Math.max(1, 3.2 - i), 0, Math.PI * 2);
      context.fillStyle = glowColor;
      context.globalAlpha = 0.55 / i;
      context.fill();
    }
    context.restore();
  }

  function animate() {
    time += 0.016;
    const light = isLightMode();

    mouse.x += (mouse.targetX - mouse.x) * 0.08;
    mouse.y += (mouse.targetY - mouse.y) * 0.08;

    ctx.clearRect(0, 0, width, height);

    const cx = width / 2;
    const cy = height / 2;
    const scaleFactor = Math.min(1.0, Math.min(width / 360, height / 230));
    const tiltX = (mouse.x / Math.max(1, width / 2)) * 7;
    const tiltY = (mouse.y / Math.max(1, height / 2)) * 5;

    const auraGrad = ctx.createRadialGradient(cx + tiltX, cy + tiltY, 16, cx, cy, 200 * scaleFactor);
    if (breakerState === 'TRIPPED') {
      const pulse = Math.sin(time * 6) * 0.12 + (light ? 0.18 : 0.32);
      auraGrad.addColorStop(0, `rgba(220, 38, 38, ${pulse})`);
      auraGrad.addColorStop(0.55, 'rgba(220, 38, 38, 0.08)');
      auraGrad.addColorStop(1, 'transparent');
    } else if (breakerState === 'WARN') {
      auraGrad.addColorStop(0, light ? 'rgba(180, 83, 9, 0.18)' : 'rgba(245, 158, 11, 0.25)');
      auraGrad.addColorStop(1, 'transparent');
    } else {
      const pulse = Math.sin(time * 2) * 0.06 + (light ? 0.14 : 0.2);
      auraGrad.addColorStop(0, `rgba(180, 140, 38, ${pulse})`);
      auraGrad.addColorStop(0.45, light ? 'rgba(4, 120, 87, 0.09)' : 'rgba(16, 185, 129, 0.12)');
      auraGrad.addColorStop(1, 'transparent');
    }
    ctx.fillStyle = auraGrad;
    ctx.fillRect(0, 0, width, height);

    if (pulseWave > 0) {
      const pRadius = (1 - pulseWave) * 185 * scaleFactor + 36;
      ctx.save();
      ctx.beginPath();
      ctx.arc(cx, cy, pRadius, 0, Math.PI * 2);
      ctx.strokeStyle = breakerState === 'TRIPPED'
        ? `rgba(220, 38, 38, ${pulseWave})`
        : `rgba(180, 140, 38, ${pulseWave})`;
      ctx.lineWidth = 2.5;
      ctx.stroke();
      ctx.restore();
      pulseWave -= 0.025;
    }

    for (let i = 0; i < particles.length / 2; i++) {
      particles[i].update();
      particles[i].draw(ctx, cx, cy, light);
    }

    const emCol = breakerState === 'TRIPPED'
      ? 'rgba(220, 38, 38, 0.55)'
      : (light ? 'rgba(4, 120, 87, 0.58)' : 'rgba(16, 185, 129, 0.65)');
    const emGlow = breakerState === 'TRIPPED' ? '#DC2626' : (light ? '#047857' : '#10B981');
    drawCircuitCoil(
      ctx, cx + tiltX * 0.5, cy + tiltY * 0.5,
      122 * scaleFactor, 44 * scaleFactor,
      -0.35 + Math.sin(time * 0.8) * 0.05,
      time * 2.1, emCol, emGlow, 1.8, breakerState === 'TRIPPED'
    );

    const rubCol = breakerState === 'TRIPPED'
      ? 'rgba(220, 38, 38, 0.88)'
      : (breakerState === 'WARN' ? 'rgba(217, 119, 6, 0.78)' : (light ? 'rgba(185, 28, 28, 0.34)' : 'rgba(239, 68, 68, 0.35)'));
    const rubGlow = breakerState === 'TRIPPED' ? '#DC2626' : (breakerState === 'WARN' ? '#D97706' : '#B91C1C');
    drawCircuitCoil(
      ctx, cx + tiltX * 0.5, cy + tiltY * 0.5,
      112 * scaleFactor, 38 * scaleFactor,
      0.45 + Math.cos(time * 0.7) * 0.05,
      -time * 1.7 + Math.PI, rubCol, rubGlow,
      breakerState === 'TRIPPED' ? 2.6 : 1.4, breakerState === 'TRIPPED'
    );

    ctx.save();
    ctx.translate(cx + tiltX, cy + tiltY);

    drawShieldPath(ctx, 0, 0, scaleFactor);
    ctx.fillStyle = light ? '#1E2433' : '#0B0C12';
    ctx.fill();

    const goldGrad = ctx.createLinearGradient(-64, -84, 64, 84);
    goldGrad.addColorStop(0, '#E8C15A');
    goldGrad.addColorStop(0.35, '#D4AF37');
    goldGrad.addColorStop(0.7, '#8C6F1E');
    goldGrad.addColorStop(1, '#D4AF37');
    ctx.strokeStyle = goldGrad;
    ctx.lineWidth = 2.4;
    ctx.shadowColor = 'rgba(212, 175, 55, 0.4)';
    ctx.shadowBlur = light ? 6 : 10;
    ctx.stroke();

    drawShieldPath(ctx, 0, 2, 0.82 * scaleFactor);
    ctx.fillStyle = light ? '#283044' : '#141622';
    ctx.fill();
    ctx.strokeStyle = 'rgba(212, 175, 55, 0.35)';
    ctx.lineWidth = 1.2;
    ctx.stroke();

    const corePulse = Math.sin(time * 3) * 0.14 + 0.86;
    const coreSize = 20 * corePulse * scaleFactor;
    ctx.beginPath();
    ctx.moveTo(0, -coreSize);
    ctx.lineTo(coreSize * 0.85, 0);
    ctx.lineTo(0, coreSize * 1.15);
    ctx.lineTo(-coreSize * 0.85, 0);
    ctx.closePath();

    const coreColor = breakerState === 'TRIPPED' ? '#EF4444' : (breakerState === 'WARN' ? '#F59E0B' : '#10B981');
    ctx.fillStyle = coreColor;
    ctx.shadowColor = coreColor;
    ctx.shadowBlur = 18;
    ctx.fill();

    ctx.beginPath();
    ctx.arc(0, 0, 4.5 * scaleFactor, 0, Math.PI * 2);
    ctx.fillStyle = '#FFFFFF';
    ctx.fill();

    ctx.restore();

    for (let i = Math.floor(particles.length / 2); i < particles.length; i++) {
      particles[i].update();
      particles[i].draw(ctx, cx, cy, light);
    }

    drawCircuitCoil(
      ctx, cx + tiltX * 0.2, cy + tiltY * 0.2,
      160 * scaleFactor, 54 * scaleFactor,
      time * 0.15, time * 1.15,
      light ? 'rgba(154, 114, 24, 0.42)' : 'rgba(212, 175, 55, 0.4)',
      light ? '#9A7218' : '#D4AF37',
      1.2, false
    );

    animId = requestAnimationFrame(animate);
  }

  window.ChronoVault = {
    setState: function (state) {
      breakerState = (state || 'CLOSED').toUpperCase();
    },
    triggerPulse: triggerPulse,
    getState: function () {
      return breakerState;
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

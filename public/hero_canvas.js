/**
 * THE CHRONO-VAULT AEGIS — 60 FPS Interactive Kinetic Canvas
 * Multi-tiered Golden Obsidian Aegis Shield with Pulsating Ruby & Emerald Circuit Coils.
 * 
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

  // State Management
  let breakerState = 'CLOSED'; // 'CLOSED', 'WARN', 'TRIPPED'
  let mouse = { x: 0, y: 0, targetX: 0, targetY: 0, isHovered: false };
  let pulseWave = 0;
  let time = 0;

  // Particle System (Token Stream)
  const PARTICLES_COUNT = 55;
  const particles = [];

  class TokenParticle {
    constructor() {
      this.reset(true);
    }

    reset(initial = false) {
      const angle = Math.random() * Math.PI * 2;
      const dist = initial ? Math.random() * 260 + 60 : Math.random() * 80 + 240;
      this.x = Math.cos(angle) * dist;
      this.y = Math.sin(angle) * dist;
      this.targetDist = Math.random() * 90 + 30;
      this.speed = Math.random() * 0.015 + 0.008;
      this.angle = angle;
      this.angularSpeed = (Math.random() - 0.5) * 0.035;
      this.size = Math.random() * 2.2 + 1.2;
      this.alpha = Math.random() * 0.7 + 0.3;
      this.type = Math.random() > 0.35 ? 'emerald' : (Math.random() > 0.5 ? 'gold' : 'ruby');
    }

    update() {
      this.angle += this.angularSpeed;
      // Inward attraction to the Aegis shield
      const currentDist = Math.sqrt(this.x * this.x + this.y * this.y);
      if (currentDist > this.targetDist) {
        this.x *= 0.992;
        this.y *= 0.992;
      } else {
        // Orbit and drift
        this.x = Math.cos(this.angle) * currentDist;
        this.y = Math.sin(this.angle) * currentDist;
      }

      // Mouse repulsion
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

      if (currentDist < 20 || currentDist > 340) {
        this.reset();
      }
    }

    draw(ctx, centerX, centerY) {
      const px = centerX + this.x;
      const py = centerY + this.y;

      let col = '#10B981';
      if (breakerState === 'TRIPPED') {
        col = Math.random() > 0.3 ? '#EF4444' : '#F59E0B';
      } else if (breakerState === 'WARN') {
        col = Math.random() > 0.5 ? '#F59E0B' : '#10B981';
      } else {
        if (this.type === 'gold') col = '#D4AF37';
        else if (this.type === 'ruby') col = '#EF4444';
      }

      ctx.save();
      ctx.beginPath();
      ctx.arc(px, py, this.size, 0, Math.PI * 2);
      ctx.fillStyle = col;
      ctx.shadowColor = col;
      ctx.shadowBlur = 8;
      ctx.globalAlpha = this.alpha;
      ctx.fill();
      ctx.restore();
    }
  }

  function init() {
    canvas = document.getElementById('chronoVaultCanvas');
    if (!canvas) return;

    ctx = canvas.getContext('2d');
    resize();
    window.addEventListener('resize', resize);

    // Mouse & Touch interactions
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

    // Populate particles
    particles.length = 0;
    for (let i = 0; i < PARTICLES_COUNT; i++) {
      particles.push(new TokenParticle());
    }

    // Start animation loop
    if (animId) cancelAnimationFrame(animId);
    animate();
  }

  function resize() {
    if (!canvas) return;
    dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    width = rect.width || canvas.parentElement.clientWidth || 600;
    height = rect.height || 360;

    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.scale(dpr, dpr);
  }

  function onMouseMove(e) {
    const rect = canvas.getBoundingClientRect();
    const cx = rect.width / 2;
    const cy = rect.height / 2;
    mouse.targetX = e.clientX - rect.left - cx;
    mouse.targetY = e.clientY - rect.top - cy;
    mouse.isHovered = true;
  }

  function onTouchMove(e) {
    if (!e.touches || e.touches.length === 0) return;
    const rect = canvas.getBoundingClientRect();
    const cx = rect.width / 2;
    const cy = rect.height / 2;
    mouse.targetX = e.touches[0].clientX - rect.left - cx;
    mouse.targetY = e.touches[0].clientY - rect.top - cy;
    mouse.isHovered = true;
  }

  function triggerPulse() {
    pulseWave = 1.0;
  }

  // Draw Aegis Shield Geometry
  function drawShieldPath(ctx, cx, cy, scale) {
    const w = 70 * scale;
    const h = 92 * scale;
    const topChamfer = 14 * scale;
    const waist = 30 * scale;

    ctx.beginPath();
    // Top flat edge with chamfered shoulders
    ctx.moveTo(cx - w + topChamfer, cy - h);
    ctx.lineTo(cx + w - topChamfer, cy - h);
    ctx.lineTo(cx + w, cy - h + topChamfer);
    // Upper convex flank
    ctx.quadraticCurveTo(cx + w + 4 * scale, cy - waist, cx + w * 0.78, cy + 10 * scale);
    // Lower tapering flank to pointed apex
    ctx.quadraticCurveTo(cx + w * 0.5, cy + h * 0.72, cx, cy + h);
    // Left side mirror
    ctx.quadraticCurveTo(cx - w * 0.5, cy + h * 0.72, cx - w * 0.78, cy + 10 * scale);
    ctx.quadraticCurveTo(cx - w - 4 * scale, cy - waist, cx - w, cy - h + topChamfer);
    ctx.closePath();
  }

  // Draw Pulsating Circuit Coils (Helical Ellipses)
  function drawCircuitCoil(ctx, cx, cy, rx, ry, tiltAngle, phase, color, glowColor, lineWidth, isTripped) {
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(tiltAngle);

    // Track path
    ctx.beginPath();
    ctx.ellipse(0, 0, rx, ry, 0, 0, Math.PI * 2);
    ctx.strokeStyle = color;
    ctx.lineWidth = lineWidth;
    ctx.shadowColor = glowColor;
    ctx.shadowBlur = isTripped ? 16 : 8;
    ctx.stroke();

    // Orbiting energy node
    const nodeAngle = phase % (Math.PI * 2);
    const nx = Math.cos(nodeAngle) * rx;
    const ny = Math.sin(nodeAngle) * ry;

    ctx.beginPath();
    ctx.arc(nx, ny, isTripped ? 4.5 : 3.5, 0, Math.PI * 2);
    ctx.fillStyle = '#FFFFFF';
    ctx.shadowColor = glowColor;
    ctx.shadowBlur = 12;
    ctx.fill();

    // Trailing sparks
    for (let i = 1; i <= 3; i++) {
      const trailAngle = nodeAngle - i * 0.15;
      const tx = Math.cos(trailAngle) * rx;
      const ty = Math.sin(trailAngle) * ry;
      ctx.beginPath();
      ctx.arc(tx, ty, Math.max(1, 3.5 - i), 0, Math.PI * 2);
      ctx.fillStyle = glowColor;
      ctx.globalAlpha = 0.6 / i;
      ctx.fill();
    }

    ctx.restore();
  }

  function animate() {
    time += 0.016;

    // Smooth mouse damping
    mouse.x += (mouse.targetX - mouse.x) * 0.08;
    mouse.y += (mouse.targetY - mouse.y) * 0.08;

    // Clear frame
    ctx.clearRect(0, 0, width, height);

    const cx = width / 2;
    const cy = height / 2;

    // Interactive parallax tilt
    const tiltX = (mouse.x / (width / 2)) * 8;
    const tiltY = (mouse.y / (height / 2)) * 6;

    // Background Aura Glow
    const auraGrad = ctx.createRadialGradient(cx + tiltX, cy + tiltY, 20, cx, cy, 220);
    if (breakerState === 'TRIPPED') {
      const pulse = Math.sin(time * 6) * 0.15 + 0.35;
      auraGrad.addColorStop(0, `rgba(239, 68, 68, ${pulse})`);
      auraGrad.addColorStop(0.5, 'rgba(239, 68, 68, 0.12)');
      auraGrad.addColorStop(1, 'transparent');
    } else if (breakerState === 'WARN') {
      auraGrad.addColorStop(0, 'rgba(245, 158, 11, 0.28)');
      auraGrad.addColorStop(0.5, 'rgba(245, 158, 11, 0.08)');
      auraGrad.addColorStop(1, 'transparent');
    } else {
      const pulse = Math.sin(time * 2) * 0.08 + 0.22;
      auraGrad.addColorStop(0, `rgba(212, 175, 55, ${pulse})`);
      auraGrad.addColorStop(0.4, 'rgba(16, 185, 129, 0.12)');
      auraGrad.addColorStop(1, 'transparent');
    }
    ctx.fillStyle = auraGrad;
    ctx.fillRect(0, 0, width, height);

    // Pulse Wave Effect on click
    if (pulseWave > 0) {
      const pRadius = (1 - pulseWave) * 200 + 40;
      ctx.save();
      ctx.beginPath();
      ctx.arc(cx, cy, pRadius, 0, Math.PI * 2);
      ctx.strokeStyle = breakerState === 'TRIPPED' ? `rgba(239, 68, 68, ${pulseWave})` : `rgba(212, 175, 55, ${pulseWave})`;
      ctx.lineWidth = 3;
      ctx.shadowColor = ctx.strokeStyle;
      ctx.shadowBlur = 15;
      ctx.stroke();
      ctx.restore();
      pulseWave -= 0.025;
    }

    // Draw Token Stream Particles (Behind shield)
    for (let i = 0; i < particles.length / 2; i++) {
      particles[i].update();
      particles[i].draw(ctx, cx, cy);
    }

    // -------------------------------------------------------------
    // COIL 1: Pulsating Emerald / Green Loop (Main Data Conductor)
    // -------------------------------------------------------------
    const emCol = breakerState === 'TRIPPED' ? 'rgba(239, 68, 68, 0.5)' : 'rgba(16, 185, 129, 0.65)';
    const emGlow = breakerState === 'TRIPPED' ? '#EF4444' : '#10B981';
    drawCircuitCoil(
      ctx,
      cx + tiltX * 0.5,
      cy + tiltY * 0.5,
      130,
      48,
      -0.35 + Math.sin(time * 0.8) * 0.05,
      time * 2.2,
      emCol,
      emGlow,
      1.8,
      breakerState === 'TRIPPED'
    );

    // -------------------------------------------------------------
    // COIL 2: Pulsating Ruby / Crimson Loop (Emergency Safety Fence)
    // -------------------------------------------------------------
    const rubCol = breakerState === 'TRIPPED' ? 'rgba(239, 68, 68, 0.9)' : (breakerState === 'WARN' ? 'rgba(245, 158, 11, 0.8)' : 'rgba(239, 68, 68, 0.35)');
    const rubGlow = breakerState === 'TRIPPED' ? '#EF4444' : (breakerState === 'WARN' ? '#F59E0B' : '#DC2626');
    drawCircuitCoil(
      ctx,
      cx + tiltX * 0.5,
      cy + tiltY * 0.5,
      120,
      42,
      0.45 + Math.cos(time * 0.7) * 0.05,
      -time * 1.8 + Math.PI,
      rubCol,
      rubGlow,
      breakerState === 'TRIPPED' ? 2.8 : 1.5,
      breakerState === 'TRIPPED'
    );

    // -------------------------------------------------------------
    // MULTI-TIERED GOLDEN OBSIDIAN AEGIS SHIELD (Centerpiece)
    // -------------------------------------------------------------
    ctx.save();
    ctx.translate(cx + tiltX, cy + tiltY);

    // TIER 1: Outer Obsidian Shield Body with Gold Rim
    drawShieldPath(ctx, 0, 0, 1.0);
    ctx.fillStyle = '#0B0C12'; // Obsidian black
    ctx.fill();

    // Outer Conic/Linear Gold Bevel
    const goldGrad = ctx.createLinearGradient(-70, -90, 70, 90);
    goldGrad.addColorStop(0, '#E8C15A');
    goldGrad.addColorStop(0.3, '#D4AF37');
    goldGrad.addColorStop(0.7, '#8C6F1E');
    goldGrad.addColorStop(1, '#D4AF37');

    ctx.strokeStyle = goldGrad;
    ctx.lineWidth = 2.5;
    ctx.shadowColor = 'rgba(212, 175, 55, 0.45)';
    ctx.shadowBlur = 10;
    ctx.stroke();

    // TIER 2: Secondary Faceted Inset Shield
    drawShieldPath(ctx, 0, 2, 0.82);
    ctx.fillStyle = '#141622';
    ctx.fill();
    ctx.strokeStyle = 'rgba(212, 175, 55, 0.35)';
    ctx.lineWidth = 1.2;
    ctx.stroke();

    // Facet lines across the shield body
    ctx.beginPath();
    ctx.moveTo(0, -92 * 0.82 + 2);
    ctx.lineTo(0, 92 * 0.82 + 2);
    ctx.moveTo(-70 * 0.82, 0);
    ctx.lineTo(70 * 0.82, 0);
    ctx.strokeStyle = 'rgba(212, 175, 55, 0.18)';
    ctx.lineWidth = 1;
    ctx.stroke();

    // TIER 3: Central High-Tech Aegis Core (Diamond Vault Lock)
    const corePulse = Math.sin(time * 3) * 0.15 + 0.85;
    const coreSize = 22 * corePulse;

    ctx.beginPath();
    ctx.moveTo(0, -coreSize);
    ctx.lineTo(coreSize * 0.85, 0);
    ctx.lineTo(0, coreSize * 1.15);
    ctx.lineTo(-coreSize * 0.85, 0);
    ctx.closePath();

    if (breakerState === 'TRIPPED') {
      ctx.fillStyle = '#EF4444';
      ctx.shadowColor = '#EF4444';
      ctx.shadowBlur = 24;
    } else if (breakerState === 'WARN') {
      ctx.fillStyle = '#F59E0B';
      ctx.shadowColor = '#F59E0B';
      ctx.shadowBlur = 18;
    } else {
      ctx.fillStyle = '#10B981';
      ctx.shadowColor = '#10B981';
      ctx.shadowBlur = 18;
    }
    ctx.fill();

    // Core Inner Glyph (Interlocking Vault Rune)
    ctx.beginPath();
    ctx.arc(0, 0, 5, 0, Math.PI * 2);
    ctx.fillStyle = '#FFFFFF';
    ctx.shadowBlur = 6;
    ctx.shadowColor = '#FFF';
    ctx.fill();

    // TIER 4: Perimeter Circuit Nodes (8 gold terminals on shield rim)
    const nodeCoords = [
      [-50, -80], [50, -80],
      [-65, 0], [65, 0],
      [-48, 55], [48, 55],
      [0, 85], [0, -85]
    ];
    nodeCoords.forEach(([nx, ny]) => {
      ctx.beginPath();
      ctx.arc(nx, ny, 2.5, 0, Math.PI * 2);
      ctx.fillStyle = breakerState === 'TRIPPED' ? '#EF4444' : '#D4AF37';
      ctx.shadowColor = ctx.fillStyle;
      ctx.shadowBlur = 6;
      ctx.fill();
    });

    ctx.restore();

    // Draw remaining Token Stream Particles (In front of shield)
    for (let i = Math.floor(particles.length / 2); i < particles.length; i++) {
      particles[i].update();
      particles[i].draw(ctx, cx, cy);
    }

    // -------------------------------------------------------------
    // COIL 3: Golden Obsidian Outer Boundary (Axial Orbit)
    // -------------------------------------------------------------
    drawCircuitCoil(
      ctx,
      cx + tiltX * 0.2,
      cy + tiltY * 0.2,
      175,
      60,
      time * 0.15,
      time * 1.2,
      'rgba(212, 175, 55, 0.4)',
      '#D4AF37',
      1.2,
      false
    );

    animId = requestAnimationFrame(animate);
  }

  // Public Interface for Integration with budget_engine.js
  window.ChronoVault = {
    setState: function (state) {
      breakerState = (state || 'CLOSED').toUpperCase();
    },
    triggerPulse: triggerPulse,
    getState: function () {
      return breakerState;
    }
  };

  // Auto-init on DOMContentLoaded
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

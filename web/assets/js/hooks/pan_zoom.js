const BUTTON_STEP = 1.6
const KEEP_VISIBLE = 0.2

const clamp = (value, min, max) => Math.min(max, Math.max(min, value))

export default {
  mounted() {
    this.svg = this.el.querySelector("svg")
    this.layer = this.el.querySelector("[data-pan-zoom-layer]")
    const [x, y, k] = this.el.dataset.view.split(" ").map(Number)
    this.initial = {x, y, k}
    this.view = {x, y, k}
    this.minZoom = Number(this.el.dataset.minZoom)
    this.maxZoom = Number(this.el.dataset.maxZoom)
    this.bounds = this.layer.getBBox()
    this.fixed = [...this.layer.querySelectorAll("[data-pan-zoom-fixed]")].map(el => ({
      el,
      x: Number(el.dataset.x),
      y: Number(el.dataset.y),
    }))
    this.reveal = [...this.layer.querySelectorAll("[data-pan-zoom-reveal]")].map(el => ({
      el,
      at: Number(el.dataset.panZoomReveal),
    }))
    this.pointers = new Map()

    this.svg.addEventListener("pointerdown", e => this.pointerDown(e))
    this.svg.addEventListener("pointermove", e => this.pointerMove(e))
    this.svg.addEventListener("pointerup", e => this.pointerUp(e))
    this.svg.addEventListener("pointercancel", e => this.pointerUp(e))
    this.svg.addEventListener("wheel", e => this.wheel(e), {passive: false})
    this.svg.addEventListener("dblclick", e => this.zoomAt(this.point(e), e.shiftKey ? 1 / BUTTON_STEP : BUTTON_STEP))
    this.svg.addEventListener("gesturestart", e => this.gestureStart(e))
    this.svg.addEventListener("gesturechange", e => this.gestureChange(e))
    this.svg.addEventListener("gestureend", () => (this.gesture = null))

    for (const button of this.el.querySelectorAll("[data-zoom]")) {
      button.addEventListener("click", () => this.button(button.dataset.zoom))
    }

    this.render()
  },

  point(e) {
    const matrix = this.svg.getScreenCTM().inverse()
    return new DOMPoint(e.clientX, e.clientY).matrixTransform(matrix)
  },

  center() {
    const {width, height} = this.svg.viewBox.baseVal
    return {x: width / 2, y: height / 2}
  },

  button(action) {
    if (action === "reset") this.view = {...this.initial}
    if (action === "in") return this.zoomAt(this.center(), BUTTON_STEP)
    if (action === "out") return this.zoomAt(this.center(), 1 / BUTTON_STEP)
    this.render()
  },

  zoomAt(point, factor) {
    const k = clamp(this.view.k * factor, this.minZoom, this.maxZoom)
    const ratio = k / this.view.k
    this.view = {
      x: point.x - (point.x - this.view.x) * ratio,
      y: point.y - (point.y - this.view.y) * ratio,
      k,
    }
    this.render()
  },

  panBy(dx, dy) {
    this.view = {...this.view, x: this.view.x + dx, y: this.view.y + dy}
    this.render()
  },

  pointerDown(e) {
    if (e.pointerType === "mouse" && e.button !== 0) return
    this.svg.setPointerCapture(e.pointerId)
    this.pointers.set(e.pointerId, this.point(e))
    this.svg.style.cursor = "grabbing"
  },

  pointerMove(e) {
    if (!this.pointers.has(e.pointerId)) return
    const before = [...this.pointers.values()]
    this.pointers.set(e.pointerId, this.point(e))
    const after = [...this.pointers.values()]

    if (after.length === 1) {
      this.panBy(after[0].x - before[0].x, after[0].y - before[0].y)
    } else if (after.length === 2) {
      const [a0, b0] = before
      const [a1, b1] = after
      const middle0 = {x: (a0.x + b0.x) / 2, y: (a0.y + b0.y) / 2}
      const middle1 = {x: (a1.x + b1.x) / 2, y: (a1.y + b1.y) / 2}
      const spread0 = Math.hypot(a0.x - b0.x, a0.y - b0.y)
      const spread1 = Math.hypot(a1.x - b1.x, a1.y - b1.y)
      this.panBy(middle1.x - middle0.x, middle1.y - middle0.y)
      if (spread0 > 0) this.zoomAt(middle1, spread1 / spread0)
    }
  },

  pointerUp(e) {
    this.pointers.delete(e.pointerId)
    if (this.pointers.size === 0) this.svg.style.cursor = ""
  },

  wheel(e) {
    e.preventDefault()
    if (this.gesture) return
    const lines = e.deltaMode === WheelEvent.DOM_DELTA_LINE ? 16 : 1
    const speed = e.ctrlKey ? 0.01 : 0.002
    this.zoomAt(this.point(e), Math.exp(-e.deltaY * lines * speed))
  },

  gestureStart(e) {
    e.preventDefault()
    this.gesture = {scale: 1}
  },

  gestureChange(e) {
    e.preventDefault()
    if (!this.gesture) return
    this.zoomAt(this.point(e), e.scale / this.gesture.scale)
    this.gesture.scale = e.scale
  },

  keepInView() {
    const {width, height} = this.svg.viewBox.baseVal
    const {x, y, width: w, height: h} = this.bounds
    const {k} = this.view
    const marginX = width * KEEP_VISIBLE
    const marginY = height * KEEP_VISIBLE
    this.view.x = clamp(this.view.x, marginX - k * (x + w), width - marginX - k * x)
    this.view.y = clamp(this.view.y, marginY - k * (y + h), height - marginY - k * y)
  },

  render() {
    this.keepInView()
    const {x, y, k} = this.view
    this.layer.setAttribute("transform", `translate(${x} ${y}) scale(${k})`)

    const shrink = this.initial.k / k
    for (const {el, x, y} of this.fixed) {
      el.setAttribute("transform", `translate(${x} ${y}) scale(${shrink}) translate(${-x} ${-y})`)
    }
    for (const {el, at} of this.reveal) {
      el.style.visibility = k / this.initial.k >= at ? "visible" : "hidden"
    }
  },
}

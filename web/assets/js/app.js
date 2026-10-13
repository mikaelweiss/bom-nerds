import "phoenix_html"
import {Socket} from "phoenix"
import {LiveSocket} from "phoenix_live_view"
import {hooks as colocatedHooks} from "phoenix-colocated/corpus"
import topbar from "../vendor/topbar"
import SaladUI from "salad_ui"
import "salad_ui/components/dialog"
import "salad_ui/components/select"
import "salad_ui/components/tabs"
import "salad_ui/components/radio_group"
import "salad_ui/components/popover"
import "salad_ui/components/hover-card"
import "salad_ui/components/collapsible"
import "salad_ui/components/tooltip"
import "salad_ui/components/accordion"
import "salad_ui/components/slider"
import "salad_ui/components/switch"
import "salad_ui/components/dropdown_menu"
import "salad_ui/components/toast"
import "salad_ui/components/toast-flash"

const csrfToken = document.querySelector("meta[name='csrf-token']").getAttribute("content")
const liveSocket = new LiveSocket("/live", Socket, {
  longPollFallbackMs: 2500,
  params: {_csrf_token: csrfToken},
  hooks: {...colocatedHooks, SaladUI: SaladUI.SaladUIHook},
})

topbar.config({barColors: {0: "#29d"}, shadowColor: "rgba(0, 0, 0, .3)"})
window.addEventListener("phx:page-loading-start", _info => topbar.show(300))
window.addEventListener("phx:page-loading-stop", _info => topbar.hide())

liveSocket.connect()
window.liveSocket = liveSocket

# JARVIS touch and microphone: shopping list with Amazon links

Budget for ALL remaining hardware: **$150 or less** (projector not counted). Prices are estimates; I could not read live prices or star ratings from Amazon (its pages block automated readers), so the ratings below come from other pages that mirror Amazon listings, and may be out of date. **Before buying anything, check on the Amazon page: 4.3 stars or more, at least 100 reviews for the cheap parts, and read the 1-2 star reviews.**

## 1. Camera (about $50-63)
**[Arducam 100fps Mono Global Shutter USB Camera, OV9281, M12 low-distortion lens](https://www.amazon.com/dp/B096M5DKY6)** (B096M5DKY6, the B0332 board)
- Rating: about **4.6-4.7 of 5**, but only 26-36 reviews (from retailer mirrors of the listing). Marked "Amazon's Choice" in search results.
- Specs that matter: plain USB webcam (UVC, no driver), monochrome, global shutter, **100 fps at 1280x800 in MJPG** (only 10 fps in YUY2: pick MJPG, which the tracker's size and fps options do), 70 degree lens, **no IR-cut filter** (so it sees 850 nm).
- Known complaint: a 2-star review says it "does not run at advertised speeds" (that is the YUY2 versus MJPG point). The listing's spec block also mixes in specs from other Arducam models: ignore anything about OV2311 or 2MP.

## 2. Filter (a few dollars, not $72): a SMALL long-pass disc, cut-on 830 nm or lower
The lens front is only about 1 cm wide, so you don't need a big sheet. Buy a small disc and glue it flat against the front of the lens (or cover the lens with a cardboard ring and hot glue). Pick **HWB830 / RG830** black glass:

- **[2 pcs HWB830, 12 x 2.0 mm](https://www.amazon.com/HWB830-12x2-0mm-Infrared-Filter-Visible/dp/B0834XTWG9)**: the right size. Careful: this page is a multi-size listing whose headline shows the M27 threaded version, so **select the "12*2.0mm" option** and check the price before ordering.
- [2 pcs HWB830, 24 x 2.0 mm](https://www.amazon.com/HWB830-2-0mm-Infrared-Filter-Visible/dp/B09H2QGDH2): bigger than needed, but fine if the 12 mm one is out of stock.
- eBay: [5 pcs HWB830, 10 x 10 x 1 mm](https://www.ebay.com/itm/275733102703) (a square piece also covers a small lens) and [various sizes](https://www.ebay.com/itm/274494491876). AliExpress has the same glass: [25 x 2 mm](https://pt.aliexpress.com/item/32917662674.html) (listed at about $10) and cheaper [10 x 10 mm pieces](https://www.aliexpress.com/i/32946610692.html), but shipping can take weeks.

I can't see live prices here, so confirm on the page. Anything much over $15 for a small disc is the wrong listing.

**Other options**
- A **720 nm photography filter** ([GREEN.L 37 mm, listed about $20-25](https://www.amazon.com/Original-Infrared-Photography-Optical-Caliber/dp/B09N2H8CJV) is the cheapest fixed one I saw). It passes the pen fully and blocks the projector's visible light, but it also lets more room and window infrared through, and it is more expensive than a small disc. Only worth it if the 830 nm disc is hard to get.
- **Free test while you wait:** a few layers of *exposed and developed* colour film negative (not unexposed, not black and white) held over the lens blocks visible light and passes infrared, and a few people report floppy-disk film working too. Results vary a lot, so use it only to test before the real filter arrives.
- Not recommended: [8.2 mm 850 nm narrow bandpass](https://www.amazon.com/dp/B09N9S27C1). An LED labelled 850 nm is often really 840-870 and it would lose much of the pen's light.

## 3. The pen parts (about $20-30)
No listing I found states a 120 degree beam for a bare 5 mm 850 nm LED. So the pen uses **three 60 degree LEDs fanned out** (one forward, one angled about 35 degrees left, one 35 degrees right), which covers about 130 degrees.

| Part | Link | Notes |
|---|---|---|
| 850 nm 5 mm IR LEDs, 100 pcs | [Chanzon 100 pcs 5mm IR 850nm, clear lens](https://www.amazon.com/dp/B01BVGIZIU) | Listing states 850 nm, **60 degrees, 1.4-1.6 V, 20 mA**. Ratings not found. Backup: [MDFLY 100 pcs](https://www.amazon.com/dp/B082NWVJHR) (angle not stated). |
| Resistors | search: [68 ohm 1/4 W resistor](https://www.amazon.com/s?k=68+ohm+1%2F4w+resistor) (or an assortment kit such as [JacobsParts 600 pcs](https://www.amazon.com/dp/B07N1YYLZZ); check its value list includes 47, 56 or 68 ohm) | You need 3. |
| Push buttons, normally open, pre-wired | [DaierTek 10-pack](https://www.amazon.com/dp/B09C8C53DM) or [Cylewet 12-pack](https://www.amazon.com/dp/B0752RMB7Q) | Check the page says **Normally Open (NO)**. Some similar listings are mislabelled NC and wouldn't work. |
| 2 x AAA battery holder with leads, no switch | [LampVPath 12-pack](https://www.amazon.com/dp/B07CSXD875) or [JWISLAND 10-pack](https://www.amazon.com/dp/B0D1DPLZ77) | The button is the switch, so get a holder **without** a switch. |
| Wire, batteries, pen body, glue | use what you have | A dry-erase marker with the ink removed makes a good body. |

### Wiring: the resistor depends on the LED's rated current
These LEDs are rated **20 mA**. With 2 AAA (about 3 V), use **68 ohm**: each LED then gets about 22-25 mA. (The 22 ohm I wrote earlier suits LEDs rated 70-100 mA, and would burn these.) Only turn on while you press, so a brief overdrive is tolerable, but don't go below 47 ohm.

```
  battery +  ---[ button ]---+---[ 68 ohm ]---( LED A )---+
                             +---[ 68 ohm ]---( LED B )---+
                             +---[ 68 ohm ]---( LED C )---+---  battery -
```
Longer LED leg = +, towards the resistor side. Three LEDs draw about 70 mA together, fine for two AAA.

A trade-off to know: a 20 mA LED is not very bright, and the beam is spread over a wider area. If the camera has trouble seeing the pen at 8.5 ft, add LEDs (a fourth and fifth) before changing anything else, or buy LEDs rated 50-100 mA (ask me and I'll search for them).

### Test before gluing
A phone's front (selfie) camera usually shows a working 850 nm LED as a purple-white glow (940 nm barely shows). The camera will do this better when it arrives.

## 4. Microphone (optional, about $50)
JARVIS already works with your computer's speakers and microphone, so this can wait.
- **[EMEET M0 / OfficeCore M0](https://www.amazon.com/dp/B07Q3D7F8S)** (B07Q3D7F8S): wired USB, 4 mics, 360 degrees. About **4.3 of 5 from about 2,000 reviews** (one aggregator's figure). Price not confirmed.
- **[EMEET M0 Plus](https://www.amazon.com/dp/B0BVZLS5GZ)** (B0BVZLS5GZ): same, plus Bluetooth. About **4.4 of 5 from 1,400-3,600 ratings** depending on the snapshot; one review-analysis site thinks fake reviews may inflate it. One snapshot showed about $50, EMEET's own table $60-70.
- Set it as **both** the Windows speaker and microphone so its built-in echo cancellation can remove JARVIS's own voice.

## Budget check ($150 limit)
| | Cost |
|---|---|
| Camera | $50-63 |
| Filter (small disc) | $5-12 |
| Pen parts | $20-30 (100-LED pack and kits cover far more than needed) |
| **Touch system** | **about $75-105** |
| Microphone (optional) | about $50 |
| **Everything** | **about $125-155**: only the top end could pass $150 |

If the total creeps over: skip the microphone, or buy the cheaper M0 over the M0 Plus. Shipping and tax are not included.

## Safety
IR LEDs are invisible. Don't stare into one from close range or leave the pen switched on. Never use an IR laser pointer for this.

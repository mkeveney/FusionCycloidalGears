# Fusion 360 Add-in to generate gears having cycloidal teeth.
# Copyright (c) 2026, Matthew Keveney.
#

# Copyright (c) 2026 Matthew Keveney
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.


# Note;  gear terminology is a confusing mess.  In this utility:
#
# 'module' is diameter /nTeeth  (Generally used with mm, but this module allows inches as well)
# 'Diametral pitch' is nTeeth / diameter (Generally used with Inches, but this add-in uses either inches or mm)
# 'Circular pitch' is circumference / nTeeth (In either inches or millimeters)
# I also allow the user to simply specify the wheel pitch diameter directly (in any units)
# Whichever method you choose, the dialog will compute the others to match.
# Internally this code uses the 'module' value
#

import adsk.core
import os, math
from ...lib import fusionAddInUtils as futil
from ... import config

app = adsk.core.Application.get()
ui = app.userInterface

CMD_ID = f'{config.COMPANY_NAME}_{config.ADDIN_NAME}_cmdDialog'
CMD_NAME = 'Make Cycloidal Gears'
CMD_Description = 'Generate gears having cycloidal tooth form'

# Specify that the command will be promoted to the panel.
IS_PROMOTED = True

# Add to end of the 'Create' menu
WORKSPACE_ID = 'FusionSolidEnvironment'
PANEL_ID = 'SolidCreatePanel'

# Resource location for command icons, here I assume a sub folder in this directory named "resources".
ICON_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources', '')

# Local list of event handlers used to maintain a reference so
# they are not released and garbage collected.
local_handlers = []

# radians to degrees (for logging only)
#
# def deg(r):
#    return r * 180 / math.pi

# compute point on cycloid for a given angle from start.
# assumes pitch circle is the unit circle
#
# a - angle from start (radians)
# np - number of teeth on pinion
# nw - number of teeth on wheel
#
# returns distance from wheel center to desired point
#
# (variables names used here mostly match those in diagram at
# https://www.csparks.com/watchmaking/CycloidalGears/index.jxl#Finding%20the%20addendum%20height
# though our formulae are somewhat different.)
#
def radiusAtAngle(a, np, nw):
    errorLimit = 0.000001
    b =  0.0                # beta
    t0 = 1.0                # theta values
    t1 = 0.0
    R2 = 2 * nw / np        # prcompute: 2 * gear ratio
    rg = 1 / R2             # rg when rw is 1

    # special case for start
    if a == 0:
        return 1

    # compute theta from two directions, adjusting until values converge
    #
    step = 0
    while (abs(t1 - t0) > errorLimit):
        t0 = t1
        b = math.atan2(math.sin(t0), (1.0 + R2 - math.cos(t0)))
        t1 = R2 * (a + b)
        step += 1

    # use rule of sines to compute resulting distance to cycloid point
    return (math.sin(t1) * rg) / math.sin(b)


# returns boolean True if the we should use inch units
# (based on document preference)
#
def usingInchUnits():
    product = app.activeProduct
    design = adsk.fusion.Design.cast(product)
    return design.unitsManager.defaultLengthUnits in ['in','ft']

# Create extrude feature
#
# comp - component
# prof - profile
# th - thickness
# op - adsk.fusion.FeatureOperations (join or cut)
# bods - array of bRepBody elements; which bodies to include in feature
#
def createExtrude(comp, prof, th, op, bods = None):
    extrudes = comp.features.extrudeFeatures
    extInput = extrudes.createInput(prof, op)
    extInput.setDistanceExtent(False, adsk.core.ValueInput.createByReal(th))
    if bods:
        extInput.participantBodies = bods
    return extrudes.add(extInput)


# For the 3-part pinion addendum, we need an iterative approach to find
# radius of the 'corner' arcs.
#
# in:
#   r = pinion pitch radius
#   ah = pinion addendum height (from pitch circle)
#   p_amid = angle from edge to center of pinion tooth:  np * (π / 2)
#
# returns the radius of the fillet
#
def findPinionAddendumCornerRadius(r, ah, p_amid):
    rm = r + ah
    maxerr = 0.00000001
    r0 = 1
    r1 = 0

    # There's probably a way to make this converge faster...
    # For simplicity, we start the search with p_amid and
    # simply do a binary search.
    #
    a = p_amid

    while abs(r1 - r0) > maxerr:
        r0 = r * math.tan(a)
        rc = r / math.cos(a)
        r1 = rm - rc
        if r1 > r0:
            a = a + a / 2
        else:
            a = a / 2

    return r1


# find distance between 2d points a, b
# in: each point is a two-tuple: (x, y)
#
def dist(a, b):
    return math.sqrt((a[0] - b[0])**2 + (a[1] - b[1])**2)

# Note: This addendum style not currently used.
#
# for two-part pinion addendum, find radius and start/endpoints of arc.
# the centrpoint of the 100% arc turns out to be useful, so we pass them in,
# since they've already been computed
#
# in:
#   r - pitch radius
#   ctr_x - X coordinate of pinion center (on x axis)
#   p_amid - angle from edge to center of pinion tooth:  np * (π / 2)
#   ah - computed addendum height
#   ra - arc of single-arc addendum (used at 100%)
#   rc - distance from pitch circle center to center of single-arc
#
#   returns tuple containing 3 two-tuples:
#   arc: (centerpoint, startpoint, endpoint, centerpoint2, endpoint2).
#       (lower arc start point = 3rd entry)
#
def findPinionOgivalArc(r, ctr_x, p_awid, p_amid, ah, ra, rc):

    # labels refer to hand-drawn diagram; todo: include somewhere in code docs.
    #
    A = (ctr_x - r, 0)  # start
    B = (ctr_x - (math.cos(p_amid) * (r  + ah)), -math.sin(p_amid) * (r + ah))  # tip
    AB = dist(A, B)
    AC = AB / 2
    # E = (ctr_x - (math.cos(p_amid) * (rc)), -math.sin(p_amid) * (rc))  # ctr of 100% arc
    AE = ra
    EB = r + ah - rc

    # use law of cosines to find α
    # ...except we really only need cos(α), so let's save a step.
    # a = math.acos((AB^2 + AE^2 - EB^2) / 2 * AB * AE)
    cos_a = ((AB**2 + AE**2 - EB**2) / (2 * AB * AE))

    # use α and AC to find AD, and thus D
    AD = AC / cos_a
    D = (A[0], -AD)     # D is addendum ctr.

    # mirror D about tooth centerline to find lower arc centerpoint.
    P = (ctr_x, 0)      # pinion center
    PD = dist(P, D)
    angD0 = math.atan(AD / r)
    angD1 = p_amid - (angD0 - p_amid)
    D1 = (ctr_x - math.cos(angD1) * PD, - math.sin(angD1) * PD)

    # lower arc endpoint is at lower edge of tooth.
    ep = (ctr_x - (math.cos(p_awid) * r), -math.sin(p_awid) * r)

    return (D, A, B, D1, ep)    # return center, start end, 2nd center, 2nd end

# draw pinion addendum
#
#   -------------------
#   Late breaking note:
#
#   In testing, I discovered that my idea for the '> 100%' described below
#   gives a shape that slightly interferes with the wheel addendum.  Thus
#   I have configured the input spinner to max out at 100%, effectively
#   disabling this option.  I'm leaving the code in place, in case
#   I (or you) want to reexamine the idea someday.
#
#   W.O.Davis, in "Gears for Small Mechanisms" describes an ogival
#   form recommended for pinions of < 10 teeth, but the arcs described are not
#   quite tangent to the dedendum edges; maybe I should implement
#   that instead.  Deferring for now.
#   -------------------
#
# Pinion addendum and wheel dedendum do not participate in the conjugate
# motion of cycloid gears; theoretically they never make contact.  Since manufacturing
# is imperfect they are still required, but we have some flexibility as to their form
# and size.  This add-in defines the addendum via a percentage ranging from 0 to
# 200%, interpreted as follows:
#
# At 100% height we use a single arc, tangent to the neighboring dedendum faces.
# This is the form recommended by BS 978 for pinions of 10 teeth or more.
# The maximum height of the remaining forms is computed from this base.
#
# At < 100%, the addendum is constructed of three arcs; the outer two tangent
# to the dedendum faces; the central one tangent to the outer two, and centered
# at the center of the pitch circle.  This gives a 'flattened' appearance yet
# still provides a filleted transition to the dedendum faces.
#
# At > 100%, the central arc disappears; the outer two arcs join at the
# center giving an ogival form.
#
# A practical minimum is probably about 25%.
#
# 0% would yield no pinion addendum, and is not recommended; at present, we
# limit to a 1% minimum.
#
# in:
#   skt - sketch
#   padp - addendum percentage/100 (ranges from 0 to 2)
#   ctrx - pinion centerpoint on x axis
#   radp - pitch radius of pinion
#   p_awid - angle from edge to edge of tooth
#   p_amid - angle from edge to midpoint of tooth
#   p_addh - addendum height (from pitch circle)
#
def drawPinionAddendum(skt, padp, ctr_x, radp, p_awid, p_amid, p_addh, ra, rc):

    if padp == 0:
        # specialcase; don't draw addendum at all
        # currently disabled via input spinner min at 1%
        return

    elif padp < 1:
        # < 100%; three arc 'flattend' style

        # compute fillet radius
        fr = findPinionAddendumCornerRadius(radp, p_addh, p_amid)

        # starting construction line
        ctr = adsk.core.Point3D.create(ctr_x, 0)
        cl0e = adsk.core.Point3D.create(ctr_x - radp - p_addh)
        cl0 = skt.sketchCurves.sketchLines.addByTwoPoints(ctr, cl0e)

        # center arc (oversize for now)
        cars = adsk.core.Point3D.create(ctr_x - (radp + p_addh), 0)
        car = skt.sketchCurves.sketchArcs.addByCenterStartSweep(ctr, cars, p_awid)

        # end construction line
        cl1e = adsk.core.Point3D.create(ctr_x - math.cos(p_awid) * (radp + p_addh), - math.sin(p_awid) * (radp + p_addh))
        cl1 = skt.sketchCurves.sketchLines.addByTwoPoints(ctr, cl1e)

        # start and end fillets
        skt.sketchCurves.sketchArcs.addFillet(cl0, cl0e, car, cars, fr)
        endf = skt.sketchCurves.sketchArcs.addFillet(cl1, cl1e, car, car.endSketchPoint.geometry, fr)

        # convert lines to construction lines so they don't define profiles.
        cl0.isConstruction = cl1.isConstruction =  True

        # return last point of end fillet.
        return endf.endSketchPoint.geometry

    elif padp == 1:
        # 100%; single arc style
        s_pt = adsk.core.Point3D.create(ctr_x - radp, 0, 0)
        a_pt = adsk.core.Point3D.create(ctr_x - math.cos(p_amid) * (radp + p_addh), -math.sin(p_amid) * (radp + p_addh), 0)
        e_pt = adsk.core.Point3D.create(ctr_x - math.cos(p_awid) * radp, -math.sin(p_awid) * radp, 0)
        skt.sketchCurves.sketchArcs.addByThreePoints(s_pt, a_pt, e_pt)
        return e_pt

    else:
        # > 100%; two arc 'ogival' style     (disabled at present)
        oa = findPinionOgivalArc(radp, ctr_x, p_awid, p_amid, p_addh, ra, rc)

        oa1 = []
        for ix in range(5):
            oa1.append(adsk.core.Point3D.create(oa[ix][0], oa[ix][1], 0))

        skt.sketchCurves.sketchArcs.addByCenterStartEnd(oa1[0], oa1[1], oa1[2])
        skt.sketchCurves.sketchArcs.addByCenterStartEnd(oa1[3], oa1[2], oa1[4])
        return oa1[4]



# Add joints and motion link.
#
def addMotion(rootc, wco, pco, numw, nump, w_pc, p_pc):

    # create base component
    bco = rootc.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    bco.isGroundToParent = True

    # I'd prefer to make my revolute joints relate the gear and
    # the parent component, than to create a 'dummy' as above.
    #
    # I can do this by hand, but not in the API. the 'createInputs'
    # method subbornly requires two _occurrences_, and does not accept
    # the root component (which has no occurrence).
    #
    #  ..have a forum post in about this.

    #
    # rco = adsk.fusion.Occurrence.cast(rootc)
    wco.isGroundToParent = False
    pco.isGroundToParent = False

    # create joint geometry object from sketch base circle
    jg = adsk.fusion.JointGeometry.createByCurve(w_pc,
        adsk.fusion.JointKeyPointTypes.CenterKeyPoint)
    # create input
    input = rootc.asBuiltJoints.createInput(wco, bco, jg)
    input.setAsRevoluteJointMotion(adsk.fusion.JointDirections.ZAxisJointDirection)
    # finally create the joint.
    wjnt = rootc.asBuiltJoints.add(input)

    # same for pinion.
    jg = adsk.fusion.JointGeometry.createByCurve(p_pc,
        adsk.fusion.JointKeyPointTypes.CenterKeyPoint)
    input = rootc.asBuiltJoints.createInput(pco, bco, jg)
    input.setAsRevoluteJointMotion(adsk.fusion.JointDirections.ZAxisJointDirection)
    pjnt = rootc.asBuiltJoints.add(input)

    # create motion link
    mli = rootc.motionLinks.createInput(wjnt, pjnt)
    mli.valueOne = adsk.core.ValueInput.createByReal(2 * math.pi)
    mli.valueTwo = adsk.core.ValueInput.createByReal((-2 * math.pi * numw) / nump)
    rootc.motionLinks.add(mli)

    return

# Executed when add-in is invoked; adds button to menu.
#
def start():
    # Create a command Definition.
    cmd_def = ui.commandDefinitions.addButtonDefinition(CMD_ID, CMD_NAME, CMD_Description, ICON_FOLDER)

    # Define event handler for the command created event;
    # called when the menu item is clicked.
    futil.add_handler(cmd_def.commandCreated, command_created)

    # Get the target workspace the button will be created in.
    workspace = ui.workspaces.itemById(WORKSPACE_ID)

    # Get the panel the button will be created in.
    panel = workspace.toolbarPanels.itemById(PANEL_ID)

    # Create the button command control in UI at the end of the menu
    control = panel.controls.addCommand(cmd_def)

    # Specify if the command is promoted to the main toolbar.
    control.isPromoted = IS_PROMOTED

# Executed when add-in is stopped.
#
def stop():
    # Get the various UI elements for this command
    workspace = ui.workspaces.itemById(WORKSPACE_ID)
    panel = workspace.toolbarPanels.itemById(PANEL_ID)
    command_control = panel.controls.itemById(CMD_ID)
    command_definition = ui.commandDefinitions.itemById(CMD_ID)

    # Delete the button command control
    if command_control:
        command_control.deleteMe()

    # Delete the command definition
    if command_definition:
        command_definition.deleteMe()


# Called when user clicks the menu button.
# Defines the contents of the command dialog and command related events.
#
def command_created(args: adsk.core.CommandCreatedEventArgs):
    # futil.log(f'{CMD_NAME} Command Created Event')

    # https://help.autodesk.com/view/fusion360/ENU/?contextId=CommandInputs
    inputs = args.command.commandInputs

    # Set up our input controls:
    # ------------------------------------------------------------

    useInch = usingInchUnits()

    lenstr = 'in' if useInch else 'mm'

    inputs.addIntegerSpinnerCommandInput('nw', 'Wheel teeth (epicycloidal)', 2, 1000, 1, 24)
    inputs.addIntegerSpinnerCommandInput('np', 'Pinion teeth (hypocycloidal)', 2, 1000,1 , 12)

    inputs.addSeparatorCommandInput('sp1')

    # Four ways to define pitch
    # we default to Module when using mm, Diametral for inches.
    #
    pmethod = inputs.addDropDownCommandInput('pm', 'Pitch Method', adsk.core.DropDownStyles.LabeledIconDropDownStyle)
    pmItems = pmethod.listItems
    pmItems.add('Module', not useInch, '')
    pmItems.add('Diametral', useInch, '')
    pmItems.add('Circular', False, '')
    pmItems.add('Wheel diameter', False, '')

    tmp = (25.4/12) if useInch else 0.2
    i = adsk.core.ValueInput.createByReal(tmp)
    inMd = inputs.addValueInput('md', 'Module', lenstr , i)
    inMd.minimumvalue = 0
    inMd.isMinimumLimited = True
    inMd.isMinimumInclusive = False
    inMd.isEnabled = not useInch

    i = adsk.core.ValueInput.createByReal(12 if useInch else .5)
    inDp = inputs.addValueInput('dp', 'Diametral pitch', '' , i)
    inDp.minimumvalue = 0
    inDp.isMinimumLimited = True
    inDp.isMinimumInclusive = False
    inDp.isEnabled = useInch

    i = adsk.core.ValueInput.createByReal(tmp * math.pi)
    inPc = inputs.addValueInput('pc', 'Circular pitch', lenstr , i)
    inPc.minimumvalue = 0
    inPc.isMinimumLimited = True
    inPc.isMinimumInclusive = False
    inPc.isEnabled = False

    i = adsk.core.ValueInput.createByReal(tmp * 24)
    inDw = inputs.addValueInput('dw', 'Wheel diameter', lenstr , i)
    inDw.minimumvalue = 0
    inDw.isMinimumLimited = True
    inDw.isMinimumInclusive = False
    inDw.isEnabled = False

    inputs.addSeparatorCommandInput('sp2')

    inputs.addFloatSpinnerCommandInput('twp', 'Tooth width %', '', 25, 100, 1, 90)

    # now limiting to max of 100%; see note above
    # also eliminating 0% option for now.
    inputs.addFloatSpinnerCommandInput('pad', 'Pinion addendum height %', '', 0, 100, 1, 100)

    inputs.addFloatSpinnerCommandInput('dclr', 'Dedendum clearance %', '', 0, 50, 1, 15)

    i = adsk.core.ValueInput.createByReal(.635 if useInch else 0.6)
    inputs.addValueInput('th', 'Thickness', lenstr , i)

    inputs.addIntegerSpinnerCommandInput('ccs', 'Cycloid Curve Steps', 2, 100, 1, 10)

    # generate joints and motion link
    inMd = inputs.addBoolValueInput('mo', 'Generate Joints', True)

    # For future consideration: alternate tooth forms.
    #
    #   Wheel tooth form: Symmetrical | fancy | one-way-parallel | perfect print
    #
    #   Symmetrical:
    #
    #   This is the currently-supported form, creating trains that may be
    #   driven in either direction.  This add-in generates a cycloidal
    #   form estimated with several short line segments.  It does not
    #   use the arc approximation described in BS 978.
    #
    #   Fancy:
    #
    #   Clocks (and some other applications, like wind-up toys) only
    #  run in a single direction, and can thus have a different
    #   form for the inactive edges of the teeth. Peterson calls
    #   these 'fancy gears.'  There are many forms the inactive edge
    #   might take, so I'm deferring for now.
    #
    #   parallel pinion faces:
    #
    #   Since the active edges of the pinion gears are straight, one 'fancy'
    #   form would be fairly simple to do: Just make the inactive side parallel
    #   to the active.  This gives the teeth a slanted look.  They will still
    #   mesh with an ordinary cycloidal form tooth; but the teeth will have
    #   uniform width, and should have the same advantages claimed for
    #   'Perfect Print' gears below.
    #
    #   Perfect Print:
    #
    #   The 'Perfect Print' form was developed by Steve Peterson, and is
    #   described in his 'Clock Design Guidelines' document, available
    #   at 'MyMiniFactory':
    #
    #       https://www.myminifactory.com/users/StevePeterson
    #
    #   The pinion teeth have edges that are parallel to and
    #   offset from a radial.  The addendum of the wheel is no
    #   longer the same as the cycloidal form, but has a
    #   similar ogive shape.  These should work in either direction.
    #
    #   The claimed advantage is that these constant-width teeth
    #   may be stronger and may print more cleanly.


    # connect handlers below
    #
    futil.add_handler(args.command.execute, command_execute, local_handlers=local_handlers)
    futil.add_handler(args.command.inputChanged, command_input_changed, local_handlers=local_handlers)
    futil.add_handler(args.command.executePreview, command_preview, local_handlers=local_handlers)
    futil.add_handler(args.command.validateInputs, command_validate_input, local_handlers=local_handlers)
    futil.add_handler(args.command.destroy, command_destroy, local_handlers=local_handlers)


# Called when the user clicks the OK button in the command dialog
#
def command_execute(args: adsk.core.CommandEventArgs):
    # futil.log(f'{CMD_NAME} Command Execute Event')

    # first retrieve inputs and compute a few related values

    # in variable names, 'w' means 'wheel' and 'p', 'pinion;
    # where wheel has ogival form teeth, and pinion has straight-sided teeth
    # Note that the wheel may be smaller than the pinion;
    # we use these terms only for convenience.

    bods = []
    inputs = args.command.commandInputs
    numw = inputs.itemById('nw').value
    nump = inputs.itemById('np').value

    ccs = inputs.itemById('ccs').value              # curve steps

    twp = inputs.itemById('twp').value / 100        # tooth width percentage
    dclrp = inputs.itemById('dclr').value / 100     # dedendum clearance percentage

    motion = inputs.itemById('mo').value

    # This code uses module for pitch; others are just input options
    # handled by the *_changed() function below
    #
    mdl = inputs.itemById('md').value
    # pc = inputs.itemById('pc').value

    # diameter and radius for wheel and pinion
    # diaw = inputs.itemById('dw').value
    diaw = mdl * numw
    radw = diaw / 2
    diap = mdl * nump    # pinion diameter
    radp = diap / 2

    thk = inputs.itemById('th').value
    padp = inputs.itemById('pad').value / 100    # pinion addendum height percentage

    # get tooth angle + convenience versions for both wheel and pinion

    w_fwid = 2 * math.pi / numw   # angle swept by tooth + neighboring dedendum
    w_awid = (w_fwid / 2) * twp # angle swept by tooth; (adjusted by twp)
    w_amid = w_awid / 2         # angle to apex of addendum

    p_fwid = 2 * math.pi / nump
    p_awid = (p_fwid / 2) * twp
    p_amid = p_awid / 2

    # We need to compute pinion addendum height here, since it's used below
    # when creating the wheel dedendum.

    # first compute addendum at 100%:
    # consider arc radius drawn from tooth midpoint to edge of tooth
    # to be the base of an isoceles triangle.  Then use the law of sines to
    # compute the length.

    ra = radp * math.tan(p_amid)    # radius of addendum arc at 100%
    rc = radp / math.cos(p_amid)    # radius from gear center to addendum arc centerpoint at 100%
    p_addh = (ra + rc) - radp       # addendum height from pitch circle

    p_addh = p_addh * padp          # adjust by percentage

    # p_addh = (radp * math.sin(p_amid)) / math.sin((math.pi - p_amid) / 2)
    # p_addh = p_addh * padp

    # compute remaining geometry below when constructing the pinion

    # Wheel:
    # ----------------------------------------------------------

    # create wheel component
    design = adsk.fusion.Design.cast(app.activeProduct)
    wcompo = design.rootComponent.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    wcomp = wcompo.component

    # insure name uniqueness? ..or just leave default name?
    wcomp.name=f'cyg_wheel_{numw}'

    # create sketch
    skt = wcomp.sketches.add(wcomp.xYConstructionPlane)

    w_pc = skt.sketchCurves.sketchCircles.addByCenterRadius(adsk.core.Point3D.create(0, 0, 0), radw)

    # extrude center
    createExtrude(wcomp, skt.profiles[0], thk, adsk.fusion.FeatureOperations.JoinFeatureOperation)

    # Create points on arc

    # The ogival tooth curves upward from 3 O'clock, thus the tooth is situated
    # 'atop' the pinion tooth in this view; with the wheel turning clockwise

    # draw lower edge of addendum profile
    ptlast = adsk.core.Point3D.create( radw , 0, 0)
    radii = []
    for n in range(1, ccs + 1):
        a = w_amid * n / ccs
        r = radiusAtAngle(a, nump, numw)
        radii.append(r)
        ptnew = adsk.core.Point3D.create(math.cos(a) * r * radw, math.sin(a) * r * radw, 0)
        skt.sketchCurves.sketchLines.addByTwoPoints(ptlast, ptnew)
        ptlast = ptnew

    # save midpoint radius for later
    rmid = r

    # retrace radii to raw upper edge
    for n in range(1, ccs):
        a = w_amid + w_amid * n / ccs
        r = radii[ccs - (n + 1) ]
        ptnew = adsk.core.Point3D.create(math.cos(a) * r * radw, math.sin(a) * r * radw, 0)
        skt.sketchCurves.sketchLines.addByTwoPoints(ptlast, ptnew)
        ptlast = ptnew

    # final point
    ptnew = adsk.core.Point3D.create(math.cos(w_awid) * radw, math.sin(w_awid) * radw, 0)
    skt.sketchCurves.sketchLines.addByTwoPoints(ptlast, ptnew)
    ptlast = ptnew

    # Dedendum includes a 'clearance' factor.  If this were applied separately
    # to wheel and pinion, we would have different clearance values.  For consistency,
    # we find the larger of the two, compute the clearance percentage on that, and use
    # the same clearance amount for both gears.
    #
    # The clearance amount is applied to the _sides_ of the dedendum.  These are
    # joined at the bottom by a straight line, so the actual clearance at the center
    # will be slightly higher, and may still differ slightly between the two gears.
    #

    addh = ((rmid - 1) * radw)
    if p_addh > addh: addh = p_addh
    clr = addh * dclrp
    # futil.log(f'wh addh: {addh} p_addh: {p_addh} clr: {clr}')

    # dedendum form is 3 straight lines.

    ded = p_addh + clr
    ptnew = adsk.core.Point3D.create(math.cos(w_awid) * (radw - ded), math.sin(w_awid) * (radw - ded), 0)
    skt.sketchCurves.sketchLines.addByTwoPoints(ptlast, ptnew)
    ptlast = ptnew

    ptnew = adsk.core.Point3D.create(math.cos(w_fwid) * (radw - ded), math.sin(w_fwid) * (radw - ded), 0)
    skt.sketchCurves.sketchLines.addByTwoPoints(ptlast, ptnew)
    ptlast = ptnew

    ptnew = adsk.core.Point3D.create(math.cos(w_fwid) * radw, math.sin(w_fwid) * radw, 0)
    skt.sketchCurves.sketchLines.addByTwoPoints(ptlast, ptnew)
    ptlast = ptnew

    # there are three profiles at this point.
    # in prior code, I've always used experimentally determined fixed indices
    # to choose the profile, but this practice is not guaranteed to work.
    #
    # So we examine the profile centroids, choosing rightmost for the addendum
    # and next-rightmost for the dedendum.  This should always work given our geometry.

    cmax = cmid = -1.0
    pmax = pmid = None
    for pr in skt.profiles:
        ap = pr.areaProperties()
        n += 1
        if ap.centroid.x > cmax:
            cmid = cmax
            pmid = pmax
            cmax = ap.centroid.x
            pmax = pr
        elif ap.centroid.x > cmid:
            cmid = ap.centroid.x
            pmid = pr

    # make sure these only act on bodies in this component
    bods = []
    bods.append(wcomp.bRepBodies[0])

    # extrude addendum
    extA = createExtrude(wcomp, pmax, thk, adsk.fusion.FeatureOperations.JoinFeatureOperation, bods)
    # dextrude dedendum (cut)
    extD = createExtrude(wcomp, pmid, thk, adsk.fusion.FeatureOperations.CutFeatureOperation, bods)

    # duplicate the extrude features around the gear
    cpfs = wcomp.features.circularPatternFeatures
    entities = adsk.core.ObjectCollection.create()
    entities.add(extA)
    entities.add(extD)
    cpfi = cpfs.createInput(entities, w_pc)
    cpfi.quantity = adsk.core.ValueInput.createByReal(numw)
    cpfs.add(cpfi)

    # Pinion
    # ----------------------------------------------------------

    pcompo = design.rootComponent.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    pcomp = pcompo.component

    pcomp.name = f'cyg_pinion_{nump}'

    # create sketch
    skt = pcomp.sketches.add(pcomp.xYConstructionPlane)

    # centerpoint of pinion
    ctr_x = (radw + radp)

    # pitch circle
    p_pc = skt.sketchCurves.sketchCircles.addByCenterRadius(adsk.core.Point3D.create(ctr_x, 0, 0), radp)
    createExtrude(pcomp, skt.profiles[0], thk, adsk.fusion.FeatureOperations.JoinFeatureOperation)

    # addendum
    #
    e_pt = drawPinionAddendum(skt, padp, ctr_x, radp,  p_awid, p_amid, p_addh, ra, rc)

    # Dedendum
    #   must have radial sides, as these are working surfaces,
    #   and must be deep enough to clear driving wheel's addendum.
    #
    #   We join the bottom with a simple line, but other shapes are acceptable;
    #   an arc might be prefereable depending on manufacturing method.
    #

    ded = ((rmid - 1) * radw) + clr

    ptnew = adsk.core.Point3D.create(ctr_x - math.cos(p_awid) * (radp - ded), -math.sin(p_awid) * (radp - ded), 0)
    skt.sketchCurves.sketchLines.addByTwoPoints(e_pt, ptnew)
    ptlast = ptnew

    ptnew = adsk.core.Point3D.create(ctr_x - math.cos(p_fwid) * (radp - ded), -math.sin(p_fwid) * (radp - ded), 0)
    skt.sketchCurves.sketchLines.addByTwoPoints(ptlast, ptnew)
    ptlast = ptnew

    ptnew = adsk.core.Point3D.create(ctr_x - math.cos(p_fwid) * radp, -math.sin(p_fwid) * radp, 0)
    skt.sketchCurves.sketchLines.addByTwoPoints(ptlast, ptnew)
    ptlast = ptnew

    # locate addendum and dedendum profiles
    # as before, except leftmost is addendum; 2nd leftmost is dedendum
    cmax = cmid = 999999.0
    pmax = pmid = None
    for pr in skt.profiles:
        ap = pr.areaProperties()
        n += 1
        if ap.centroid.x < cmax:
            cmid = cmax
            pmid = pmax
            cmax = ap.centroid.x
            pmax = pr
        elif ap.centroid.x < cmid:
            cmid = ap.centroid.x
            pmid = pr

    # make sure these only act on bodies in this component
    bods = []
    bods.append(pcomp.bRepBodies[0])

    # extrude addendum
    extA = createExtrude(pcomp, pmax, thk, adsk.fusion.FeatureOperations.JoinFeatureOperation, bods)
    # cut dedendum
    extD = createExtrude(pcomp, pmid, thk, adsk.fusion.FeatureOperations.CutFeatureOperation, bods)

    # duplicate the above features in a circle
    cpfs = pcomp.features.circularPatternFeatures
    entities = adsk.core.ObjectCollection.create()
    entities.add(extA)
    entities.add(extD)
    # use the sketch pitch-circle to define the rotation axis
    cpfi = cpfs.createInput(entities, p_pc)
    cpfi.quantity = adsk.core.ValueInput.createByReal(nump)
    cpfs.add(cpfi)

    if (motion):
        # add base object, as-built joints, and motion link
        addMotion(design.rootComponent, wcompo, pcompo, numw, nump, w_pc, p_pc)

# Called when the command needs to compute a new preview in the graphics window.
#
def command_preview(args: adsk.core.CommandEventArgs):
    pass
    # futil.log(f'{CMD_NAME} Command Preview Event')
    # inputs = args.command.commandInputs

# Called when the user changes anything in the command dialog,
# allowing us to modify values of other inputs or otherwise
# update the display.
#
def command_input_changed(args: adsk.core.InputChangedEventArgs):
    changed_input = args.input
    inputs = args.inputs

    # futil.log(f'{CMD_NAME} Input Changed Event fired from a change to {changed_input.id}')

    # Note on diametral pitch:
    #
    # Diametral pitch is itself unitless, but is related to length units.
    # It should be read as 'teeth per inch of diameter'
    # or, less commonly, 'teeth per mm of diameter'.
    # (we do not support any other length units.)
    #
    # So converting to/from module is not straightforward.
    #
    # Internally Fusion always works in 'cm' units, regardless of the
    # command entry units.  Thus, the conversions are:
    #
    # using 'mm' units:
    #       dp = .1 / mod
    #       mod = .1 / dp
    #
    # using 'in' units:
    #       dp = 2.54 / mod
    #       mod = 2.54 / dp
    #
    # So, we simply select a different multiplier based on the document units.
    #
    # note that the bulk of this add-in always uses module so this conversion only
    # needs to happen here in the UI.

    useInch = usingInchUnits()
    dp_multiplier = 2.54 if useInch else 0.1

    # enable/disable pitch controls to activate the one
    # matching the selected pitch method
    #
    if (changed_input.id == 'pm'):
        pmix = changed_input.selectedItem.index
        inputs.itemById('md').isEnabled = (pmix == 0)
        inputs.itemById('dp').isEnabled = (pmix == 1)
        inputs.itemById('pc').isEnabled = (pmix == 2)
        inputs.itemById('dw').isEnabled = (pmix == 3)
        return

    # update disabled pitch controls to match any change to the enabled one
    #
    if (changed_input.id == 'md'):
        inputs.itemById('dp').value = dp_multiplier / changed_input.value
        inputs.itemById('pc').value = changed_input.value * math.pi
        inputs.itemById('dw').value = changed_input.value * inputs.itemById('nw').value
        return

    if (changed_input.id == 'dp'):
        tmp = dp_multiplier / changed_input.value
        inputs.itemById('md').value = tmp
        inputs.itemById('pc').value = tmp * math.pi
        inputs.itemById('dw').value = tmp * inputs.itemById('nw').value
        return

    if (changed_input.id == 'pc'):
        tmp = (changed_input.value/math.pi)
        inputs.itemById('md').value = tmp
        inputs.itemById('dp').value = dp_multiplier / tmp
        inputs.itemById('dw').value = (changed_input.value/math.pi) * inputs.itemById('nw').value
        return
    if (changed_input.id == 'dw'):
        tmp = (changed_input.value / inputs.itemById('nw').value)
        inputs.itemById('md').value = tmp
        inputs.itemById('dp').value = dp_multiplier / tmp
        inputs.itemById('pc').value = tmp * math.pi
        return

    # update disabled pitch controls to match any change to wheel tooth count
    #
    if (changed_input.id == 'nw'):
        if (inputs.itemById('pm').selectedItem.index == 2):
            # pitch method is diameter; update md, dp, and pc
            tmp = inputs.itemById('dw').value / changed_input.value
            inputs.itemById('md').value = tmp
            inputs.itemById('dp').value = dp_multiplier / tmp
            inputs.itemById('pc').value = tmp * math.pi
        else:
            # pitch method is not diameter; just update dw
            inputs.itemById('dw').value = inputs.itemById('md').value * changed_input.value
        return

# Called when the user interacts with any of the inputs in the dialog
# We validate that values are valid; if we so the OK button gets enabled
#
def command_validate_input(args: adsk.core.ValidateInputsEventArgs):
    # futil.log(f'{CMD_NAME} Validate Input Event')
    # inputs = args.inputs
    # we don't need to validate minimums;
    # the valueInputs already do that via the limit properties
    args.areInputsValid = True

# Called when the command terminates.
#
def command_destroy(args: adsk.core.CommandEventArgs):
    # futil.log(f'{CMD_NAME} Command Destroy Event')

    global local_handlers
    local_handlers = []

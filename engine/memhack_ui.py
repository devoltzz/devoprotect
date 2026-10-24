# Finds the interface memory hacks of patches 1.24-1.28 (the MemHackAPI) and gives each one its Warcraft III 3.0 equivalent.
import re


LIBRARIES = (
    ('MemHackAPI (Unryze, 1.24e-1.28f)',
     ('UnlockMemory', 'UnlockMemEx', 'ReadRealMemory', 'WriteRealMemory', 'GetBytecodeAddress', 'InitBytecode',
      'GetJassTable', 'CreateJassNativeHook', 'ExecuteBytecode', 'AllocateExecutableMemory', 'ChangeOffsetProtection',
      'GetMemoryArrayAddress', 'TypecastMemoryArray'),
     ('MemHackTable', 'pGameDLL', 'PatchVersion')),
    ('Memory Hack (1.26a/1.27a: leandrotp, DracoL1ch; the core MemHackAPI grew from)',
     ('ReadMemory', 'WriteMemory', 'ReadRealMemory', 'GetArrayAddress', 'TypecastArray', 'NewGlobal', 'SetGlobal',
      'UnlockMemory', 'GetBytecodeAddress', 'TypecastByteCode'),
     ('l__bytecode', 'l__Array', 'pbytecode')),
)

F = 'KKMH_f(%s)'
FP = 'KKMH_fp(%s)'
FID = 'KKMH_fid(%s)'
D = ' * bj_DEGTORAD'


def _q(i):
    return F % '{%d}' % i


TRANSLATIONS = {
    'GetFrameByName': (['string', 'integer'], 'integer', ['return ' + FID % 'BlzGetFrameByName({0}, {1})']),
    'GetFrameTextByName': (['string', 'integer'], 'string', ['return BlzFrameGetText(BlzGetFrameByName({0}, {1}))']),
    'GetTooltipUberFrame': ([], 'integer', ['return ' + FID % 'BlzGetOriginFrame(ORIGIN_FRAME_UBERTOOLTIP, 0)']),
    'CreateFrame': (
        ['string', 'integer', 'integer'],
        'integer',
        ['return ' + FID % ('BlzCreateFrame({0}, %s, 0, {2})' % (FP % '{1}'))],
    ),
    'LoadTOCFile': (['string'], 'integer', ['if BlzLoadTOCFile({0}) then', '    return 1', 'endif', 'return 0']),
    'HideFrame': (['integer'], 'integer', ['call BlzFrameSetVisible(%s, false)' % _q(0), 'return {0}']),
    'ShowFrame': (['integer'], 'integer', ['call BlzFrameSetVisible(%s, true)' % _q(0), 'return {0}']),
    'SetFrameAlpha': (['integer', 'integer'], 'integer', ['call BlzFrameSetAlpha(%s, {1})' % _q(0), 'return {0}']),
    'GetFrameAlpha': (['integer'], 'integer', ['return BlzFrameGetAlpha(%s)' % _q(0)]),
    'SetFrameTooltip': (
        ['integer', 'integer'],
        'integer',
        ['call BlzFrameSetTooltip(%s, %s)' % (_q(0), _q(1)), 'return {0}'],
    ),
    'SetFrameFocus': (['integer', 'boolean'], 'integer', ['call BlzFrameSetFocus(%s, {1})' % _q(0), 'return {0}']),
    'SetFrameCageMouse': (['integer', 'boolean'], 'integer', ['call BlzFrameCageMouse(%s, {1})' % _q(0), 'return {0}']),
    'SetFrameAbsolutePoint': (
        ['integer', 'integer', 'real', 'real'],
        'integer',
        ['call BlzFrameSetAbsPoint(%s, ConvertFramePointType({1}), {2}, {3})' % _q(0), 'return {0}'],
    ),
    'SetFramePoint': (
        ['integer', 'integer', 'integer', 'integer', 'real', 'real'],
        'integer',
        [
            'call BlzFrameSetPoint(%s, ConvertFramePointType({1}), %s, ConvertFramePointType({3}), {4}, {5})'
            % (_q(0), FP % '{2}'),
            'return {0}',
        ],
    ),
    'SetUIFramePoint': (
        ['integer', 'integer', 'integer', 'integer', 'real', 'real'],
        'integer',
        [
            'call BlzFrameSetPoint(%s, ConvertFramePointType({1}), %s, ConvertFramePointType({3}), {4}, '
            '{5})' % (_q(0), FP % '{2}'),
            'return {0}',
        ],
    ),
    'ClearFrameAllPoints': (['integer'], 'integer', ['call BlzFrameClearAllPoints(%s)' % _q(0), 'return {0}']),
    'SetFrameAllPoints': (
        ['integer', 'integer'],
        'integer',
        ['call BlzFrameSetAllPoints(%s, %s)' % (_q(0), FP % '{1}'), 'return {0}'],
    ),
    'SetFrameWidth': (
        ['integer', 'real'],
        'integer',
        ['call BlzFrameSetSize(%s, {1}, BlzFrameGetHeight(%s))' % (_q(0), _q(0)), 'return {0}'],
    ),
    'SetFrameHeight': (
        ['integer', 'real'],
        'integer',
        ['call BlzFrameSetSize(%s, BlzFrameGetWidth(%s), {1})' % (_q(0), _q(0)), 'return {0}'],
    ),
    'SetFrameSize': (
        ['integer', 'real', 'real'],
        'integer',
        ['call BlzFrameSetSize(%s, {1}, {2})' % _q(0), 'return {0}'],
    ),
    'GetFrameWidth': (['integer'], 'real', ['return BlzFrameGetWidth(%s)' % _q(0)]),
    'GetFrameHeight': (['integer'], 'real', ['return BlzFrameGetHeight(%s)' % _q(0)]),
    'SetFrameScale': (['integer', 'real'], 'integer', ['call BlzFrameSetScale(%s, {1})' % _q(0), 'return {0}']),
    'SetLayoutFrameScale': (['integer', 'real'], 'integer', ['call BlzFrameSetScale(%s, {1})' % _q(0), 'return {0}']),
    'SetFrameVertexColour': (
        ['integer', 'integer'],
        'integer',
        ['call BlzFrameSetVertexColor(%s, {1})' % _q(0), 'return {0}'],
    ),
    'SetFrameVertexColourEx': (
        ['integer', 'integer', 'integer', 'integer', 'integer'],
        'integer',
        ['call BlzFrameSetVertexColor(%s, BlzConvertColor({1}, {2}, {4}, {3}))' % _q(0), 'return {0}'],
    ),
    'SetFrameTextColour': (
        ['integer', 'integer'],
        'integer',
        ['call BlzFrameSetTextColor(%s, {1})' % _q(0), 'return {0}'],
    ),
    'SetFrameTextColourEx': (
        ['integer', 'integer', 'integer', 'integer', 'integer'],
        'integer',
        ['call BlzFrameSetTextColor(%s, BlzConvertColor({1}, {2}, {4}, {3}))' % _q(0), 'return {0}'],
    ),
    'DestroyFrame': (['integer'], 'integer', ['call BlzDestroyFrame(%s)' % _q(0), 'return 0']),
    'IsFrameEnabled': (['integer'], 'boolean', ['return BlzFrameGetEnable(%s)' % _q(0)]),
    'EnableFrame': (['integer'], 'integer', ['call BlzFrameSetEnable(%s, true)' % _q(0), 'return {0}']),
    'DisableFrame': (['integer'], 'integer', ['call BlzFrameSetEnable(%s, false)' % _q(0), 'return {0}']),
    'ClickFrame': (['integer'], 'integer', ['call BlzFrameClick(%s)' % _q(0), 'return {0}']),
    'SetFrameModel': (
        ['integer', 'string', 'integer', 'boolean'],
        'integer',
        ['call BlzFrameSetModel(%s, {1}, {2})' % _q(0), 'return {0}'],
    ),
    'SetFrameTexture': (
        ['integer', 'string', 'boolean'],
        'integer',
        ['call BlzFrameSetTexture(%s, {1}, 0, {2})' % _q(0), 'return {0}'],
    ),
    'GetFrameParent': (['integer'], 'integer', ['return ' + FID % ('BlzFrameGetParent(%s)' % _q(0))]),
    'SetFrameParent': (
        ['integer', 'integer'],
        'integer',
        ['call BlzFrameSetParent(%s, %s)' % (_q(0), FP % '{1}'), 'return {0}'],
    ),
    'GetFrameName': (['integer'], 'string', ['return BlzFrameGetName(%s)' % _q(0)]),
    'GetFrameValue': (['integer'], 'real', ['return BlzFrameGetValue(%s)' % _q(0)]),
    'SetFrameValue': (['integer', 'real'], 'integer', ['call BlzFrameSetValue(%s, {1})' % _q(0), 'return {0}']),
    'SetFrameMinMaxValue': (
        ['integer', 'real', 'real'],
        'integer',
        ['call BlzFrameSetMinMaxValue(%s, {1}, {2})' % _q(0), 'return {0}'],
    ),
    'SetFrameStepValue': (['integer', 'real'], 'nothing', ['call BlzFrameSetStepSize(%s, {1})' % _q(0)]),
    'SetFrameFont': (
        ['integer', 'string', 'real', 'integer'],
        'integer',
        ['call BlzFrameSetFont(%s, {1}, {2}, {3})' % _q(0), 'return {0}'],
    ),
    'SetLayerFont': (
        ['integer', 'string', 'real', 'integer'],
        'integer',
        ['call BlzFrameSetFont(%s, {1}, {2}, {3})' % _q(0), 'return {0}'],
    ),
    'GetFrameTextMaxLength': (['integer'], 'integer', ['return BlzFrameGetTextSizeLimit(%s)' % _q(0)]),
    'SetFrameMaxTextLength': (['integer', 'integer'], 'nothing', ['call BlzFrameSetTextSizeLimit(%s, {1})' % _q(0)]),
    'GetFrameText': (['integer'], 'string', ['return BlzFrameGetText(%s)' % _q(0)]),
    'SetFrameText': (['integer', 'string'], 'integer', ['call BlzFrameSetText(%s, {1})' % _q(0), 'return {0}']),
    'HideUI': ([], 'nothing', ['call BlzHideOriginFrames(true)']),
    'ShowUI': ([], 'nothing', ['call BlzHideOriginFrames(false)']),
    'HideMiniMap': ([], 'nothing', ['call BlzFrameSetVisible(BlzGetOriginFrame(ORIGIN_FRAME_MINIMAP, 0), false)']),
    'ShowMiniMap': ([], 'nothing', ['call BlzFrameSetVisible(BlzGetOriginFrame(ORIGIN_FRAME_MINIMAP, 0), true)']),
    'HideBlackBorders': (
        [],
        'nothing',
        [
            'call BlzFrameSetAllPoints(BlzGetOriginFrame(ORIGIN_FRAME_WORLD_FRAME, 0), '
            'BlzGetOriginFrame(ORIGIN_FRAME_GAME_UI, 0))',
            'call BlzFrameSetVisible(BlzGetFrameByName("ConsoleUIBackdrop", 0), false)',
        ],
    ),
    'GetEffectX': (['effect'], 'real', ['return BlzGetLocalSpecialEffectX({0})']),
    'GetEffectY': (['effect'], 'real', ['return BlzGetLocalSpecialEffectY({0})']),
    'GetEffectZ': (['effect'], 'real', ['return BlzGetLocalSpecialEffectZ({0})']),
    'SetEffectX': (['effect', 'real'], 'nothing', ['call BlzSetSpecialEffectX({0}, {1})']),
    'SetEffectY': (['effect', 'real'], 'nothing', ['call BlzSetSpecialEffectY({0}, {1})']),
    'SetEffectZ': (['effect', 'real'], 'nothing', ['call BlzSetSpecialEffectZ({0}, {1})']),
    'SetEffectPosition': (
        ['effect', 'real', 'real', 'real'],
        'nothing',
        ['call BlzSetSpecialEffectPosition({0}, {1}, {2}, {3})'],
    ),
    'SetEffectTimeScale': (['effect', 'real'], 'nothing', ['call BlzSetSpecialEffectTimeScale({0}, {1})']),
    'GetEffectScale': (['effect'], 'real', ['return BlzGetSpecialEffectScale({0})']),
    'SetEffectScale': (['effect', 'real'], 'nothing', ['call BlzSetSpecialEffectScale({0}, {1})']),
    'SetEffectScaleEx': (
        ['effect', 'real', 'real', 'real'],
        'nothing',
        ['call BlzSetSpecialEffectMatrixScale({0}, {1}, {2}, {3})'],
    ),
    'SetEffectRoll': (['effect', 'real'], 'nothing', ['call BlzSetSpecialEffectRoll({0}, {1}%s)' % D]),
    'SetEffectPitch': (['effect', 'real'], 'nothing', ['call BlzSetSpecialEffectPitch({0}, {1}%s)' % D]),
    'SetEffectYaw': (['effect', 'real'], 'nothing', ['call BlzSetSpecialEffectYaw({0}, {1}%s)' % D]),
    'SetEffectFacing': (['effect', 'real'], 'nothing', ['call BlzSetSpecialEffectYaw({0}, {1}%s)' % D]),
    'SetEffectOrientation': (
        ['effect', 'real', 'real', 'real'],
        'nothing',
        ['call BlzSetSpecialEffectOrientation({0}, {1}%s, {2}%s, {3}%s)' % (D, D, D)],
    ),
    'SetEffectSpaceRotation': (
        ['effect', 'real', 'real', 'real'],
        'nothing',
        ['call BlzSetSpecialEffectOrientation({0}, {1}%s, {2}%s, {3}%s)' % (D, D, D)],
    ),
    'ResetEffectMatrix': (['effect'], 'nothing', ['call BlzResetSpecialEffectMatrix({0})']),
    'SetEffectAlpha': (['effect', 'integer'], 'nothing', ['call BlzSetSpecialEffectAlpha({0}, {1})']),
    'SetEffectColourEx': (
        ['effect', 'integer', 'integer', 'integer', 'integer'],
        'nothing',
        ['call BlzSetSpecialEffectColor({0}, {1}, {2}, {3})', 'call BlzSetSpecialEffectAlpha({0}, {4})'],
    ),
    'SetEffectVertexColour': (
        ['effect', 'integer', 'integer', 'integer', 'integer'],
        'nothing',
        ['call BlzSetSpecialEffectColor({0}, {1}, {2}, {3})', 'call BlzSetSpecialEffectAlpha({0}, {4})'],
    ),
    'SetEffectColour': (
        ['effect', 'integer'],
        'nothing',
        [
            'local integer a = BlzBitAnd({1}, 0x7F000000) / 0x1000000',
            'if {1} < 0 then',
            '    set a = a + 128',
            'endif',
            'call BlzSetSpecialEffectColor({0}, BlzBitAnd({1}, 0xFF0000) / 0x10000, BlzBitAnd({1}, 0xFF00) / 0x100, '
            'BlzBitAnd({1}, 0xFF))',
            'call BlzSetSpecialEffectAlpha({0}, a)',
        ],
    ),
    'GetUnitBaseDamage': (['unit'], 'integer', ['return BlzGetUnitBaseDamage({0}, 0)']),
    'SetUnitBaseDamage': (['unit', 'integer'], 'nothing', ['call BlzSetUnitBaseDamage({0}, {1}, 0)']),
    'SetUnitMaxMana': (['unit', 'real'], 'nothing', ['call BlzSetUnitMaxMana({0}, R2I({1}))']),
    'SetUnitMaxLife': (['unit', 'real'], 'nothing', ['call BlzSetUnitMaxHP({0}, R2I({1}))']),
    'SetUnitLifeRegen': (
        ['unit', 'real'],
        'nothing',
        ['call BlzSetUnitRealField({0}, UNIT_RF_HIT_POINTS_REGENERATION_RATE, {1})'],
    ),
    'SetUnitManaRegen': (
        ['unit', 'real'],
        'nothing',
        ['call BlzSetUnitRealField({0}, UNIT_RF_MANA_REGENERATION, {1})'],
    ),
    'GetUnitCollisionSize': (['unit'], 'real', ['return BlzGetUnitCollisionSize({0})']),
    'IsUnitInvulnerable': (['unit'], 'boolean', ['return BlzIsUnitInvulnerable({0})']),
    'GetUnitAbilityByIndex': (['unit', 'integer'], 'ability', ['return BlzGetUnitAbilityByIndex({0}, {1})']),
    'GetItemAbilityByIndex': (['item', 'integer'], 'ability', ['return BlzGetItemAbilityByIndex({0}, {1})']),
    'GetUnitAbilityManaCost': (
        ['unit', 'integer', 'integer'],
        'integer',
        ['return BlzGetUnitAbilityManaCost({0}, {1}, {2})'],
    ),
    'SetUnitAbilityManaCost': (
        ['unit', 'integer', 'integer', 'integer'],
        'nothing',
        ['call BlzSetUnitAbilityManaCost({0}, {1}, {2}, {3})'],
    ),
    'StartUnitAbilityCooldown': (
        ['unit', 'integer', 'real'],
        'nothing',
        ['call BlzStartUnitAbilityCooldown({0}, {1}, {2})'],
    ),
    'GetUnitAbilityCurrentCooldown': (
        ['unit', 'integer'],
        'real',
        ['return BlzGetUnitAbilityCooldownRemaining({0}, {1})'],
    ),
    'ResetUnitAbilityCooldown': (['unit', 'integer'], 'nothing', ['call BlzEndUnitAbilityCooldown({0}, {1})']),
    'SetUnitFacingEx': (
        ['unit', 'real', 'boolean'],
        'nothing',
        ['if {2} then', '    call BlzSetUnitFacingEx({0}, {1})', 'else', '    call SetUnitFacing({0}, {1})', 'endif'],
    ),
}


def _defined(body_text):
    out = {}
    for m in re.finditer(
        r'(?m)^[ \t]*(?:constant[ \t]+)?function[ \t]+(\w+)[ \t]+takes[ \t]+(.*?)[ \t]+returns[ \t]+(\w+)', body_text
    ):
        ps = m.group(2).strip()
        out[m.group(1)] = ([] if ps == 'nothing' else [p.split()[-2] for p in ps.split(',') if len(p.split()) >= 2],
                           m.group(3))
    return out


def detect_libraries(body_text, defs=None):
    defs = _defined(body_text) if defs is None else defs
    libs = {}
    for fname, core, globals_block in LIBRARIES:
        hits = [n for n in core if n in defs]
        if not hits:
            continue
        marks = [
            g for g in globals_block if re.search(r'(?m)^[ \t]*\w+[ \t]+(?:array[ \t]+)?%s\b' % re.escape(g), body_text)
        ]
        if len(hits) >= 3 or marks:
            libs[fname] = hits + marks
            if marks:
                break
    return libs


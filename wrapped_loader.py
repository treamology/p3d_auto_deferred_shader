from panda3d.core import ConfigVariableBool, TextureStage, Texture, TransparencyAttrib, VBase4, getModelPath, Shader

class WrappedLoader(object):

    def __init__(self, original_loader):
        self.original_loader = original_loader
        self.texture_shader_inputs = []
        self.use_srgb = ConfigVariableBool('framebuffer-srgb').getValue()
        self.shader_cache = {}

    def _from_snake_case(self, attr):
        camel_case=''
        up=False
        for char in attr:
            if up:
                char=char.upper()
            if char == "_":
                up=True
            else:
                up=False
                camel_case+=char
        return camel_case

    def __getattr__(self,attr):
        new_attr=self._from_snake_case(attr)
        if hasattr(self, new_attr):
            return self.__getattribute__(new_attr)

    def fix_transparency(self, model):
        for tex_stage in model.find_all_texture_stages():
            tex = model.find_texture(tex_stage)
            if tex:
                mode = tex_stage.get_mode()
                tex_format = tex.get_format()
                if mode == TextureStage.M_modulate and (tex_format == Texture.F_rgba or tex_format == Texture.F_srgb_alpha):
                    return
        model.set_transparency(TransparencyAttrib.MNone, 1)
        #model.clear_transparency()

    def fixSrgbTextures(self, model):
        for tex_stage in model.find_all_texture_stages():
            tex = model.find_texture(tex_stage)
            if tex:
                file_name = tex.get_filename()
                tex_format = tex.get_format()
                # print( tex_stage,  file_name, tex_format)
                if tex_stage.get_mode() == TextureStage.M_normal:
                    tex_stage.get_mode(TextureStage.M_normal_gloss)
                if tex_stage.get_mode() != TextureStage.M_normal_gloss:
                    if tex_format == Texture.F_rgb:
                        tex_format = Texture.F_srgb
                    elif tex_format == Texture.F_rgba:
                        tex_format = Texture.F_srgb_alpha
                tex.set_format(tex_format)
                model.set_texture(tex_stage, tex, 1)

    def setTextureInputs(self, node):
        for child in node.get_children():
            #print(child)
            self._setTextureInputs(child)
            self.setTextureInputs(child)


    def _setTextureInputs(self, model):
        #print ('Fixing model', model)
        slots_filled = set()
        # find all the textures, easy mode - slot is fitting the stage mode
        # (eg. slot0 is diffuse/color)
        for slot, tex_stage in enumerate(model.find_all_texture_stages()):
            if slot >= len(self.texture_shader_inputs):
                break
            tex = model.find_texture(tex_stage)
            if tex:
                #print('Found tex:', tex.getFilename())
                mode = tex_stage.get_mode()
                if mode in self.texture_shader_inputs[slot]['stage_modes']:
                    model.set_shader_input(self.texture_shader_inputs[
                                         slot]['input_name'], tex)
                    slots_filled.add(slot)
        # did we get all of them?
        if len(slots_filled) == len(self.texture_shader_inputs):
            return
        # what slots need filling?
        missing_slots = set(
            range(len(self.texture_shader_inputs))) - slots_filled
        for slot, tex_stage in enumerate(model.findAllTextureStages()):
            if slot >= len(self.texture_shader_inputs):
                break
            if slot in missing_slots:
                tex = model.find_texture(tex_stage)
                if tex:
                    mode = tex_stage.get_mode()
                    for d in self.texture_shader_inputs:
                        if mode in d['stage_modes']:
                            i = self.texture_shader_inputs.index(d)
                            model.set_shader_input(self.texture_shader_inputs[
                                                 i]['input_name'], tex)
                            slots_filled.add(i)
        # did we get all of them this time?
        if len(slots_filled) == len(self.texture_shader_inputs):
            return
        missing_slots = set(
            range(len(self.texture_shader_inputs))) - slots_filled
        #print ('Fail for model:', model)
        # set defaults
        for slot in missing_slots:
            model.set_shader_input(self.texture_shader_inputs[slot][
                                 'input_name'], self.texture_shader_inputs[slot]['default_texture'])

    def destroy(self):
        self.original_loader.destroy()

    def loadModel(self, modelPath, loaderOptions=None, noCache=None,
                  allowInstance=False, okMissing=None,
                  callback=None, extraArgs=[], priority=None):
        model = self.original_loader.loadModel(
            modelPath, loaderOptions, noCache, allowInstance, okMissing, callback, extraArgs, priority)

        if self.use_srgb:
            self.fixSrgbTextures(model)
        self.setTextureInputs(model)
        self.fix_transparency(model)
        return model

    def cancelRequest(self, cb):
        self.original_loader.cancelRequest(cb)

    def isRequestPending(self, cb):
        return self.original_loader.isRequestPending(cb)

    def loadModelOnce(self, modelPath):
        return self.original_loader.loadModelOnce(modelPath)

    def loadModelCopy(self, modelPath, loaderOptions=None):
        return self.original_loader.loadModelCopy(modelPath, loaderOptions)

    def loadModelNode(self, modelPath):
        return self.original_loader.loadModelNode(modelPath)

    def unloadModel(self, model):
        self.original_loader.unloadModel(model)

    def saveModel(self, modelPath, node, loaderOptions=None,
                  callback=None, extraArgs=[], priority=None):
        return self.original_loader.saveModel(modelPath, node, loaderOptions, callback, extraArgs, priority)

    def loadFont(self, modelPath,
                 spaceAdvance=None, lineHeight=None,
                 pointSize=None,
                 pixelsPerUnit=None, scaleFactor=None,
                 textureMargin=None, polyMargin=None,
                 minFilter=None, magFilter=None,
                 anisotropicDegree=None,
                 color=None,
                 outlineWidth=None,
                 outlineFeather=0.1,
                 outlineColor=VBase4(0, 0, 0, 1),
                 renderMode=None,
                 okMissing=False):
        return self.original_loader.loadFont(modelPath, spaceAdvance, lineHeight, pointSize, pixelsPerUnit, scaleFactor, textureMargin, polyMargin, minFilter, magFilter, anisotropicDegree, color, outlineWidth, outlineFeather, outlineColor, renderMode, okMissing)

    def loadTexture(self, texturePath, alphaPath=None,
                    readMipmaps=False, okMissing=False,
                    minfilter=None, magfilter=None,
                    anisotropicDegree=None, loaderOptions=None,
                    multiview=None, sRgb=False):
        tex = self.original_loader.loadTexture(
            texturePath, alphaPath, readMipmaps, okMissing, minfilter, magfilter, anisotropicDegree, loaderOptions, multiview)
        if sRgb:
            tex_format = tex.getFormat()
            if tex_format == Texture.F_rgb:
                tex_format = Texture.F_srgb
            elif tex_format == Texture.F_rgba:
                tex_format = Texture.F_srgb_alpha
            tex.setFormat(tex_format)
        return tex

    def load3DTexture(self, texturePattern, readMipmaps=False, okMissing=False,
                      minfilter=None, magfilter=None, anisotropicDegree=None,
                      loaderOptions=None, multiview=None, numViews=2):
        return self.original_loader.load3DTexture(texturePattern, readMipmaps, okMissing, minfilter, magfilter, anisotropicDegree, loaderOptions, multiview, numViews)

    def load2DTextureArray(self, texturePattern, readMipmaps=False, okMissing=False,
                           minfilter=None, magfilter=None, anisotropicDegree=None,
                           loaderOptions=None, multiview=None, numViews=2):
        return self.original_loader.load2DTextureArray(texturePattern, readMipmaps, okMissing, minfilter, magfilter, anisotropicDegree, loaderOptions, multiview, numViews)

    def loadCubeMap(self, texturePattern, readMipmaps=False, okMissing=False,
                    minfilter=None, magfilter=None, anisotropicDegree=None,
                    loaderOptions=None, multiview=None):
        return self.original_loader.loadCubeMap(texturePattern, readMipmaps, okMissing, minfilter, magfilter, anisotropicDegree, loaderOptions, multiview)

    def unloadTexture(self, texture):
        self.original_loader.unloadTexture(texture)

    def loadSfx(self, *args, **kw):
        return self.original_loader.loadSfx(*args, **kw)

    def loadMusic(self, *args, **kw):
        return self.original_loader.loadMusic(*args, **kw)

    def loadSound(self, manager, soundPath, positional=False,
                  callback=None, extraArgs=[]):
        return self.original_loader.loadSound(manager, soundPath, positional, callback, extraArgs)

    def unloadSfx(self, sfx):
        self.original_loader.unloadSfx(sfx)

    def loadShaderGLSL(self, v_shader, f_shader, define=None, version='#version 140'):
        # check if we already have a shader like that
        # note: this may fail depending on the dict implementation
        if (v_shader, f_shader, str(define)) in self.shader_cache:
            return self.shader_cache[(v_shader, f_shader, str(define))]
        # load the shader text
        with open(getModelPath().findFile(v_shader).toOsSpecific()) as f:
            v_shader_txt = f.read()
        with open(getModelPath().findFile(f_shader).toOsSpecific()) as f:
            f_shader_txt = f.read()
        # make the header
        if define:
            header = version + '\n'
            for name, value in define.items():
                header += '#define {0} {1}\n'.format(name, value)
            # put the header on top
            v_shader_txt = v_shader_txt.replace(version, header)
            f_shader_txt = f_shader_txt.replace(version, header)
        # make the shader
        shader = Shader.make(Shader.SL_GLSL, v_shader_txt, f_shader_txt)
        # store it
        self.shader_cache[(v_shader, f_shader, str(define))] = shader
        try:
            shader.set_filename(Shader.ST_vertex, v_shader)
            shader.set_filename(Shader.ST_fragment, f_shader)
        except:
            print('Shader filenames will not be available, consider using a dev version of Panda3D')
        return shader

    def loadShader(self, shaderPath, okMissing=False):
        return self.original_loader.loadShader(shaderPath, okMissing)

    def unloadShader(self, shaderPath):
        self.original_loader.unloadShader(shaderPath)

    def asyncFlattenStrong(self, model, inPlace=True,
                           callback=None, extraArgs=[]):
        self.original_loader.asyncFlattenStrong(
            model, inPlace, callback, extraArgs)
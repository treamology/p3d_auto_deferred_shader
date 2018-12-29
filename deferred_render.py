import sys
import math
from direct.showbase.DirectObject import DirectObject
from panda3d.core import *

from wrapped_loader import WrappedLoader

if sys.version_info >= (3, 0):
    import builtins
else:
    import __builtin__ as builtins

__author__ = "wezu"
__copyright__ = "Copyright 2017-2018"
__license__ = "ISC"
__version__ = "0.21"
__email__ = "wezu.dev@gmail.com"
__all__ = ['DeferredRenderer']


class DeferredRenderer(DirectObject):
    """
    DeferredRenderer is a singelton class that takes care of rendering
    It installs itself in the buildins,
    it also creates a deferred_render and forward_render nodes.
    """

    def __init__(self, filter_setup=None, shading_setup=None, shadows=None, scene_mask=1, light_mask=2):
        # check if there are other DeferredRenderer in buildins
        if hasattr(builtins, 'deferred_renderer'):
            raise RuntimeError('There can only be one DeferredRenderer')

        builtins.deferred_renderer = self
        # template to load the shaders by name, without the directory and
        # extension
        self.f = 'shaders/{}_f.glsl'
        self.v = 'shaders/{}_v.glsl'
        # last known window size, needed to test on window events if the window
        # size changed
        self.last_window_size = (base.win.get_x_size(), base.win.get_y_size())

        self.shadow_size=shadows
        self.attached_lights={}
        self.modelMask = scene_mask
        self.lightMask = light_mask

        # install a wrapped version of the loader in the builtins
        builtins.loader = WrappedLoader(builtins.loader)
        loader.texture_shader_inputs = [{'input_name': 'tex_diffuse',
                                         'stage_modes': (TextureStage.M_modulate, TextureStage.M_modulate_glow, TextureStage.M_modulate_gloss),
                                         'default_texture': loader.load_texture('tex/def_diffuse.png')},
                                        {'input_name': 'tex_normal',
                                         'stage_modes': (TextureStage.M_normal, TextureStage.M_normal_height, TextureStage.M_normal_gloss),
                                         'default_texture': loader.load_texture('tex/def_normal.png')},
                                        {'input_name': 'tex_material',  # Shine Height Alpha Glow
                                         # something different
                                         'stage_modes': (TextureStage.M_selector,),
                                         'default_texture': loader.load_texture('tex/def_material.png')}]
        # set up the deferred rendering buffers
        self.shading_setup = shading_setup
        self._setup_g_buffer(self.shading_setup)

        # post process
        self.filter_buff = {}
        self.filter_quad = {}
        self.filter_tex = {}
        self.filter_cam = {}


        self.cube_tex=loader.load_cube_map('tex/cube/skybox_#.png')
        tex_format=self.cube_tex.get_format()
        if tex_format == Texture.F_rgb:
            tex_format = Texture.F_srgb
        elif tex_format == Texture.F_rgba:
            tex_format = Texture.F_srgb_alpha
        self.cube_tex.set_format(tex_format)
        self.cube_tex.set_magfilter(SamplerState.FT_linear_mipmap_linear )
        self.cube_tex.set_minfilter(SamplerState.FT_linear_mipmap_linear)

        self.common_inputs = {'render': render,
                              'camera': base.cam,
                              'depth_tex': self.depth,
                              'normal_tex': self.normal,
                              'albedo_tex': self.albedo,
                              'lit_tex': self.lit_tex,
                              'forward_tex': self.plain_tex,
                              'forward_aux_tex': self.plain_aux,
                              'cube_tex': self.cube_tex}

        self.filter_stages = filter_setup

        for stage in self.filter_stages:
            self.add_filter(**stage)
        for name, tex in self.filter_tex.items():
            self.common_inputs[name] = tex
        for filter_name, quad in self.filter_quad.items():
            try:
                quad.set_shader_inputs(**self.common_inputs)
            except AttributeError:
                for name, value in self.common_inputs.items():
                    quad.set_shader_input(name, value)

        # stick the last stage quad to render2d
        # this is a bit ugly...
        if 'name' in self.filter_stages[-1]:
            last_stage = self.filter_stages[-1]['name']
        else:
            last_stage = self.filter_stages[-1]['shader']
        self.filter_quad[last_stage] = self.lightbuffer.get_texture_card()
        self.reload_filter(last_stage)
        self.filter_quad[last_stage].reparent_to(render2d)

        # listen to window events so that buffers can be resized with the
        # window
        self.accept("window-event", self._on_window_event)
        # update task
        taskMgr.add(self._update, '_update_tsk', sort=-150)

    def save_screenshot(self, name='screen', extension='png'):
        if 'name' in self.filter_stages[-1]:
            last_stage = self.filter_stages[-1]['name']
        else:
            last_stage = self.filter_stages[-1]['shader']
        tex=self.filter_tex[last_stage]
        base.graphicsEngine.extract_texture_data(tex, base.win.getGsg())
        #base.graphicsEngine.renderFrame()
        tex.write(name+'.'+extension)
        print('Screen saved to:', name+'.'+extension)

    def set_cubemap(self, cubemap):
        self.cube_tex=loader.load_cube_map(cubemap)
        tex_format=self.cube_tex.get_format()
        if tex_format == Texture.F_rgb:
            tex_format = Texture.F_srgb
        elif tex_format == Texture.F_rgba:
            tex_format = Texture.F_srgb_alpha
        self.cube_tex.set_format(tex_format)
        self.cube_tex.set_magfilter(SamplerState.FT_linear_mipmap_linear )
        self.cube_tex.set_minfilter(SamplerState.FT_linear_mipmap_linear)
        self.common_inputs['cube_tex']= self.cube_tex
        for quad in self.filter_quad.values():
            quad.set_shader_input('cube_tex', self.cube_tex)


    def set_material(self, node, roughness, metallic, glow, alpha=1.0):
        image = PNMImage(x_size=32, y_size=32, num_channels=4)
        image.fill(roughness, glow, metallic)
        image.alpha_fill(alpha)
        tex=Texture()
        tex.load(image)
        node.set_shader_input('tex_material',tex, 1)

    def set_near_far(self, near, far):
        base.cam.node().get_lens().set_near_far(near, far)
        lens = base.cam.node().get_lens()
        self.modelcam.node().set_lens(lens)
        self.lightcam.node().set_lens(lens)

    def reset_filters(self, filter_setup, shading_setup=None):
        """
        Remove all filters and creates a new filter list using the given filter_setup (dict)
        """
        # special case - get the inputs for the directionl light(s)
        dir_light_num_lights = self.get_filter_define(
            'final_light', 'NUM_LIGHTS')
        dir_light_color = self.get_filter_input('final_light', 'light_color')
        dir_light_dir = self.get_filter_input('final_light', 'direction')

        # remove buffers
        for buff in self.filter_buff.values():
            buff.clear_render_textures()
            base.win.get_gsg().get_engine().remove_window(buff)
        # remove quads, but keep the last one (detach it)
        # the last one should also be self.lightbuffer.get_texture_card()
        # so we don't need to keep a reference to it
        if 'name' in self.filter_stages[-1]:
            last_stage = self.filter_stages[-1]['name']
        else:
            last_stage = self.filter_stages[-1]['shader']
        for name, quad in self.filter_quad.items():
            if name != last_stage:
                quad.remove_node()
            else:
                quad.detach_node()
        for cam in self.filter_cam.values():
            cam.remove_node()
        # load the new values
        self.filter_buff = {}
        self.filter_quad = {}
        self.filter_tex = {}
        self.filter_cam = {}
        self.filter_stages = filter_setup
        for stage in self.filter_stages:
            self.add_filter(**stage)
        for name, tex in self.filter_tex.items():
            self.common_inputs[name] = tex
        for filter_name, quad in self.filter_quad.items():
            try:
                quad.set_shader_inputs(**self.common_inputs)
            except AttributeError:
                for name, value in self.common_inputs.items():
                    quad.set_shader_input(name, value)
        # stick the last stage quad to render2d
        # this is a bit ugly...
        if 'name' in self.filter_stages[-1]:
            last_stage = self.filter_stages[-1]['name']
        else:
            last_stage = self.filter_stages[-1]['shader']
        self.filter_quad[last_stage] = self.lightbuffer.get_texture_card()
        self.reload_filter(last_stage)
        self.filter_quad[last_stage].reparent_to(render2d)

        # reapply the directional lights
        self.set_filter_define(
            'final_light', 'NUM_LIGHTS', dir_light_num_lights)
        if dir_light_color:
            self.set_filter_input('final_light', None, dir_light_color)
            self.set_filter_input('final_light', None, dir_light_dir)

        if shading_setup != self.shading_setup:
            self.light_root.set_shader(loader.load_shader_GLSL(
                self.v.format('point_light'), self.f.format('point_light'), shading_setup))
            self.geometry_root.set_shader(loader.load_shader_GLSL(
                self.v.format('geometry'), self.f.format('geometry'), shading_setup))
            self.plain_root.set_shader(loader.load_shader_GLSL(
                self.v.format('forward'), self.f.format('forward'), shading_setup))
            self.shading_setup=shading_setup

        size=1
        if 'FORWARD_SIZE' in self.shading_setup:
            size= self.shading_setup['FORWARD_SIZE']
        window_size = (base.win.get_x_size(), base.win.get_y_size())
        self.plain_buff.set_size(int(window_size[0]*size), int(window_size[1]*size))


    def reload_filter(self, stage_name):
        """
        Reloads the shader and inputs of a given filter stage
        """
        id = self._get_filter_stage_index(stage_name)
        shader = self.filter_stages[id]['shader']
        inputs = {}
        if 'inputs' in self.filter_stages[id]:
            inputs = self.filter_stages[id]['inputs']
        define = None
        if 'define' in self.filter_stages[id]:
            define = self.filter_stages[id]['define']
        self.filter_quad[stage_name].set_shader(loader.load_shader_GLSL(
            self.v.format(shader), self.f.format(shader), define))
        for name, value in inputs.items():
            if isinstance(value, str):
                value = loader.load_texture(value)
                inputs[name]=value
        #inputs={**inputs, **self.common_inputs} #works on py3 only :(
        inputs.update(self.common_inputs)
        try:
            self.filter_quad[stage_name].set_shader_inputs(**inputs)
        except AttributeError:
            for name, value in inputs.items():
                self.filter_quad[stage_name].set_shader_input(name, value)

        if 'translate_tex_name' in self.filter_stages[id]:
            for old_name, new_name in self.filter_stages[id]['translate_tex_name'].items():
                value = self.filter_tex[old_name]
                self.filter_quad[stage_name].set_shader_input(
                    str(new_name), value)

    def get_filter_define(self, stage_name, name):
        """
        Returns the current value of a shader pre-processor define for a given filter stage
        """
        if stage_name in self.filter_quad:
            id = self._get_filter_stage_index(stage_name)
            if 'define' in self.filter_stages[id]:
                if name in self.filter_stages[id]['define']:
                    return self.filter_stages[id]['define'][name]
        return None

    def set_filter_define(self, stage_name, name, value):
        """
        Sets a define value for the shader pre-processor for a given filter stage,
        The shader for that filter stage gets reloaded, so no need to call reload_filter()
        """
        if stage_name in self.filter_quad:
            id = self._get_filter_stage_index(stage_name)
            if 'define' in self.filter_stages[id]:
                if value is None:
                    if name in self.filter_stages[id]['define']:
                        del self.filter_stages[id]['define'][name]
                else:
                    self.filter_stages[id]['define'][name] = value
            elif value is not None:
                self.filter_stages[id]['define'] = {name: value}
            # reload the shader
            self.reload_filter(stage_name)

    def _get_filter_stage_index(self, name):
        """
        Returns the index of a filter stage
        """
        for index, stage in enumerate(self.filter_stages):
            if 'name' in stage:
                if stage['name'] == name:
                    return index
            elif stage['shader'] == name:
                return index
        raise IndexError('No stage named ' + name)

    def get_filter_input(self, stage_name, name):
        """
        Returns the shader input from a given stage
        """
        if stage_name in self.filter_quad:
            id = self._get_filter_stage_index(stage_name)
            return self.filter_quad[stage_name].get_shader_input(str(name))
        return None

    def set_filter_input(self, stage_name, name, value, modify_using=None):
        """
        Sets a shader input for a given filter stage.
        modify_using - should be an operator, like operator.add if you want to
                       change the value of an input based on the current value
        """
        if stage_name in self.filter_quad:
            id = self._get_filter_stage_index(stage_name)
            if name is None:
                self.filter_quad[stage_name].set_shader_input(value)
                return
            if modify_using is not None:
                value = modify_using(self.filter_stages[id][
                                     'inputs'][name], value)
                self.filter_stages[id]['inputs'][name] = value
            if isinstance(value, str):
                tex = loader.load_texture(value, sRgb='srgb'in value)
                if 'nearest' in value:
                    tex.set_magfilter(SamplerState.FT_nearest)
                    tex.set_minfilter(SamplerState.FT_nearest)
                if 'f_rgb16' in value:
                    tex.set_format(Texture.F_rgb16)
                if 'clamp' in value:
                    tex.set_wrap_u(Texture.WMClamp)
                    tex.set_wrap_v(Texture.WMClamp)
                value=tex
            self.filter_quad[stage_name].set_shader_input(str(name), value)
            # print(stage_name, name, value)

    def _get_win_depth_bits(self):
        fbprops=base.win.get_fb_properties()
        return fbprops.get_depth_bits()

    def _setup_g_buffer(self, define=None):
        """
        Creates all the needed buffers, nodes and attributes for a geometry buffer
        """
        depth_bits=self._get_win_depth_bits()
        self.modelbuffer = self._make_FBO(name="model buffer", auxrgba=1, depth_bits=depth_bits)
        self.lightbuffer = self._make_FBO(name="light buffer", auxrgba=0, depth_bits=depth_bits)

        # Create four render textures: depth, normal, albedo, and final.
        # attach them to the various bitplanes of the offscreen buffers.
        self.depth = Texture()
        self.depth.set_wrap_u(Texture.WM_clamp)
        self.depth.set_wrap_v(Texture.WM_clamp)
        if depth_bits==32:
            self.depth.set_format(Texture.F_depth_component32)
        elif depth_bits==24:
            self.depth.set_format(Texture.F_depth_component24)
        elif depth_bits==16:
            self.depth.set_format(Texture.F_depth_component16)
        else:
            self.depth.set_format(Texture.F_depth_component)
        self.depth.set_component_type(Texture.T_float)
        self.albedo = Texture()
        self.albedo.set_wrap_u(Texture.WM_clamp)
        self.albedo.set_wrap_v(Texture.WM_clamp)
        self.normal = Texture()
        self.normal.set_format(Texture.F_rgba16)
        self.normal.set_component_type(Texture.T_float)
        #self.normal.set_magfilter(SamplerState.FT_linear)
        #self.normal.set_minfilter(SamplerState.FT_linear_mipmap_linear)
        self.lit_tex = Texture()
        self.lit_tex.set_wrap_u(Texture.WM_clamp)
        self.lit_tex.set_wrap_v(Texture.WM_clamp)

        self.modelbuffer.add_render_texture(tex=self.depth,
                                          mode=GraphicsOutput.RTMBindOrCopy,
                                          bitplane=GraphicsOutput.RTPDepth)
        self.modelbuffer.add_render_texture(tex=self.albedo,
                                          mode=GraphicsOutput.RTMBindOrCopy,
                                          bitplane=GraphicsOutput.RTPColor)
        self.modelbuffer.add_render_texture(tex=self.normal,
                                          mode=GraphicsOutput.RTMBindOrCopy,
                                          bitplane=GraphicsOutput.RTP_aux_hrgba_0)
        self.lightbuffer.add_render_texture(tex=self.lit_tex,
                                          mode=GraphicsOutput.RTMBindOrCopy,
                                          bitplane=GraphicsOutput.RTPColor)
        # Set the near and far clipping planes.
        base.cam.node().get_lens().set_near_far(2.0, 70.0)
        lens = base.cam.node().get_lens()

        # This algorithm uses three cameras: one to render the models into the
        # model buffer, one to render the lights into the light buffer, and
        # one to render "plain" stuff (non-deferred shaded) stuff into the
        # light buffer.  Each camera has a bitmask to identify it.
        # self.modelMask = 1
        # self.lightMask = 2

        self.modelcam = base.make_camera(win=self.modelbuffer,
                                        lens=lens,
                                        scene=render,
                                        mask=BitMask32.bit(self.modelMask))
        self.lightcam = base.make_camera(win=self.lightbuffer,
                                        lens=lens,
                                        scene=render,
                                        mask=BitMask32.bit(self.lightMask))

        # Panda's main camera is not used.
        base.cam.node().set_active(0)

        # Take explicit control over the order in which the three
        # buffers are rendered.
        self.modelbuffer.set_sort(1)
        self.lightbuffer.set_sort(2)
        base.win.set_sort(3)

        # Within the light buffer, control the order of the two cams.
        self.lightcam.node().get_display_region(0).set_sort(1)

        # By default, panda usually clears the screen before every
        # camera and before every window.  Tell it not to do that.
        # Then, tell it specifically when to clear and what to clear.
        self.modelcam.node().get_display_region(0).disable_clears()
        self.lightcam.node().get_display_region(0).disable_clears()
        base.cam.node().get_display_region(0).disable_clears()
        base.cam2d.node().get_display_region(0).disable_clears()
        self.modelbuffer.disable_clears()
        base.win.disable_clears()

        self.modelbuffer.set_clear_color_active(1)
        self.modelbuffer.set_clear_depth_active(1)
        self.lightbuffer.set_clear_color_active(1)
        self.lightbuffer.set_clear_color((0, 0, 0, 0))
        self.modelbuffer.set_clear_color((0, 0, 0, 0))
        self.modelbuffer.set_clear_active(GraphicsOutput.RTP_aux_hrgba_0, True)

        render.set_state(RenderState.make_empty())

        # Create two subroots, to help speed cull traversal.
        # root node and a list for the lights
        self.light_root = render.attach_new_node('light_root')
        self.light_root.set_shader(loader.load_shader_GLSL(
            self.v.format('point_light'), self.f.format('point_light'), define))
        self.light_root.hide(BitMask32.bit(self.modelMask))
        try:
            self.light_root.set_shader_inputs(albedo_tex=self.albedo,
                                          depth_tex=self.depth,
                                          normal_tex=self.normal,
                                          camera=base.cam,
                                          render=render )
        except AttributeError:
            self.light_root.set_shader_input('albedo_tex', self.albedo)
            self.light_root.set_shader_input('depth_tex',self.depth)
            self.light_root.set_shader_input('normal_tex',self.normal)
            self.light_root.set_shader_input('camera',base.cam)
            self.light_root.set_shader_input('render',render )

        # self.light_root.hide(BitMask32(self.plainMask))

        self.geometry_root = render.attach_new_node('geometry_root')
        self.geometry_root.set_shader(loader.load_shader_GLSL(
            self.v.format('geometry'), self.f.format('geometry'), define))
        self.geometry_root.hide(BitMask32.bit(self.lightMask))
        # self.geometry_root.hide(BitMask32(self.plainMask))

        self.plain_root, self.plain_tex, self.plain_cam, self.plain_buff, self.plain_aux = self._make_forward_stage(define)
        self.plain_root.set_shader(loader.load_shader_GLSL(
            self.v.format('forward'), self.f.format('forward'), define))
        self.plain_root.set_shader_input("depth_tex", self.depth)
        mask=BitMask32.bit(self.modelMask)
        #mask.set_bit(self.lightMask)
        self.plain_root.hide(mask)

        #set aa
        #render.setAntialias(AntialiasAttrib.M_multisample)

        # instal into buildins
        builtins.deferred_render = self.geometry_root
        builtins.forward_render = self.plain_root

    def _on_window_event(self, window):
        """
        Function called when something hapens to the main window
        Currently it's only function is to resize all the buffers to fit
        the new size of the window if the size of the window changed
        """
        if window is not None:
            window_size = (base.win.get_x_size(), base.win.get_y_size())
            if self.last_window_size != window_size:
                lens = base.cam.node().get_lens()
                lens.set_aspect_ratio(float(window_size[0])/float(window_size[1]))
                self.modelcam.node().set_lens(lens)
                self.lightcam.node().set_lens(lens)
                self.plain_cam.node().set_lens(lens)

                self.modelbuffer.set_size(window_size[0], window_size[1])
                self.lightbuffer.set_size(window_size[0], window_size[1])
                #fix here!
                size=1
                if 'FORWARD_SIZE' in self.shading_setup:
                    size= self.shading_setup['FORWARD_SIZE']
                self.plain_buff.set_size(int(window_size[0]*size), int(window_size[1]*size))
                for buff in self.filter_buff.values():
                    old_size = buff.get_fb_size()
                    x_factor = float(old_size[0]) / \
                        float(self.last_window_size[0])
                    y_factor = float(old_size[1]) / \
                        float(self.last_window_size[1])
                    buff.set_size(
                        int(window_size[0] * x_factor), int(window_size[1] * y_factor))
                self.last_window_size = window_size

    def add_filter(self, shader, inputs={},
                   name=None, size=1.0,
                   clear_color=(0, 0, 0, 0), translate_tex_name=None,
                   define=None):
        """
        Creates and adds filter stage to the filter stage dicts:
        the created buffer is put in self.filter_buff[name]
        the created fullscreen quad is put in self.filter_quad[name]
        the created fullscreen texture is put in self.filter_tex[name]
        the created camera is put in self.filter_cam[name]
        """
        #print(inputs)
        if name is None:
            name = shader
        index = len(self.filter_buff)
        quad, tex, buff, cam = self._make_filter_stage(
            sort=index, size=size, clear_color=clear_color, name=name)
        self.filter_buff[name] = buff
        self.filter_quad[name] = quad
        self.filter_tex[name] = tex
        self.filter_cam[name] = cam

        quad.set_shader(loader.load_shader_GLSL(self.v.format(
            shader), self.f.format(shader), define))
        for name, value in inputs.items():
            if isinstance(value, str):
                value = loader.load_texture(value, sRgb=loader.use_srgb)
                inputs[name]=value
        try:
            quad.set_shader_inputs(**inputs)
        except AttributeError:
            for name, value in inputs.items():
                quad.set_shader_input(name, value)


        if translate_tex_name:
            for old_name, new_name in translate_tex_name.items():
                value = self.filter_tex[old_name]
                quad.set_shader_input(str(new_name), value)

    def _make_filter_stage(self, sort=0, size=1.0, clear_color=None, name=None):
        """
        Creates a buffer, quad, camera and texture needed for a filter stage
        Use add_filter() not this function
        """
        # make a root for the buffer
        root = NodePath("filterBufferRoot")
        tex = Texture()
        tex.set_wrap_u(Texture.WM_clamp)
        tex.set_wrap_v(Texture.WM_clamp)
        buff_size_x = int(base.win.get_x_size() * size)
        buff_size_y = int(base.win.get_y_size() * size)
        # buff=base.win.makeTextureBuffer("buff", buff_size_x, buff_size_y, tex)
        winprops = WindowProperties()
        winprops.set_size(buff_size_x, buff_size_y)
        props = FrameBufferProperties()
        props.set_rgb_color(True)
        props.set_rgba_bits(8, 8, 8, 8)
        props.set_depth_bits(0)
        buff = base.graphicsEngine.make_output(
            base.pipe, 'filter_stage_'+name, sort,
            props, winprops,
            GraphicsPipe.BF_resizeable,
            base.win.get_gsg(), base.win)
        buff.add_render_texture(
            tex=tex, mode=GraphicsOutput.RTMBindOrCopy, bitplane=GraphicsOutput.RTPColor)
        buff.set_sort(sort)
        #print(name, sort)
        # buff.setSort(0)
        if clear_color is None:
            buff.set_clear_active(GraphicsOutput.RTPColor, False)
        else:
            buff.set_clear_color(clear_color)
            buff.set_clear_active(GraphicsOutput.RTPColor, True)

        cam = base.make_camera(win=buff)
        cam.reparent_to(root)
        cam.set_pos(buff_size_x * 0.5, buff_size_y * 0.5, 100)
        cam.set_p(-90)
        lens = OrthographicLens()
        lens.set_film_size(buff_size_x, buff_size_y)
        cam.node().set_lens(lens)
        # plane with the texture, a blank texture for now
        cm = CardMaker("plane")
        cm.set_frame(0, buff_size_x, 0, buff_size_y)
        quad = root.attach_new_node(cm.generate())
        quad.look_at(0, 0, -1)
        quad.set_light_off()
        '''Vertices=GeomVertexData('Triangle', GeomVertexFormat.getV3(), Geom.UHStatic)
        Vertex=GeomVertexWriter(Vertices, 'vertex')
        Vertex.addData3d(0.0,0.0,0.0)
        Vertex.addData3d(0.0,0.0,0.0)
        Vertex.addData3d(0.0,0.0,0.0)
        Triangle = GeomTriangles(Geom.UHStatic)
        Triangle.addVertices(0,1,2)
        Triangle.closePrimitive()
        Primitive=Geom(Vertices)
        Primitive.addPrimitive(Triangle)
        gNode=GeomNode('FullScreenTriangle')
        gNode.addGeom(Primitive)
        quad = NodePath(gNode)
        quad.reparent_to(root)'''

        return quad, tex, buff, cam

    def _make_forward_stage(self, define):
        """
        Creates nodes, buffers and whatnot needed for forward rendering
        """
        size=1
        if 'FORWARD_SIZE' in define:
            size= define['FORWARD_SIZE']

        root = NodePath("forwardRoot")
        tex = Texture()
        tex.set_wrap_u(Texture.WM_clamp)
        tex.set_wrap_v(Texture.WM_clamp)
        aux_tex = Texture()
        aux_tex.set_wrap_u(Texture.WM_clamp)
        aux_tex.set_wrap_v(Texture.WM_clamp)
        buff_size_x = int(base.win.get_x_size()*size)
        buff_size_y = int(base.win.get_y_size()*size)


        winprops = WindowProperties()
        winprops.set_size(buff_size_x, buff_size_y)
        props = FrameBufferProperties()
        props.set_rgb_color(True)
        props.set_rgba_bits(8, 8, 8, 8)
        props.set_srgb_color(True)
        if 'FORWARD_AUX' in define:
            props.set_aux_rgba(1)
        props.set_depth_bits(0)
        buff = base.graphicsEngine.make_output(
            base.pipe, 'forward_stage', 2,
            props, winprops,
            GraphicsPipe.BF_resizeable,
            base.win.get_gsg(), base.win)
        buff.add_render_texture(tex=tex, mode=GraphicsOutput.RTMBindOrCopy, bitplane=GraphicsOutput.RTPColor)
        if 'FORWARD_AUX' in define:
            buff.add_render_texture(tex=aux_tex,mode=GraphicsOutput.RTMBindOrCopy, bitplane=GraphicsOutput.RTPAuxRgba0)
            buff.set_clear_active(GraphicsOutput.RTPAuxRgba0, True)
        buff.set_clear_color((0, 0, 0, 0))
        cam = base.make_camera(win=buff)
        cam.reparent_to(root)
        lens = base.cam.node().get_lens()
        cam.node().set_lens(lens)
        mask = BitMask32.bit(self.modelMask)
        mask.set_bit(self.lightMask)
        cam.node().set_camera_mask(mask)
        return root, tex, cam, buff, aux_tex

    def set_directional_light(self, color, direction, shadow_size=0):
        """
        Sets value for a directional light,
        use the SceneLight class to set the lights!
        """

        try:
            self.filter_quad['final_light'].set_shader_inputs(light_color=color, direction=direction)
        except AttributeError:
            self.filter_quad['final_light'].set_shader_input('light_color',color)
            self.filter_quad['final_light'].set_shader_input('direction', direction)



    def add_sun_light(self, color, offset=100.0, direction=(0,0,1), radius=1.0):
        """
        Creates a spotlight,
        use the ConeLight class, not this function!
        ..in fact don't use this at all, experimental/broken
        """
        #if fov > 179.0:
        #    fov = 179.0
        #xy_scale = math.tan(deg2Rad(fov * 0.5))
        model = loader.load_model("models/sphere")
        # temp=model.copyTo(self.plain_root)
        # self.lights.append(model)
        model.reparent_to(self.light_root)
        #model.set_scale(xy_scale, 1.0, xy_scale)
        #model.flatten_strong()
        model.set_scale(radius*2.0)
        #model.set_pos(pos)
        #model.setHpr(hpr)
        # debug=self.lights[-1].copyTo(self.plain_root)
        model.set_attrib(DepthTestAttrib.make(RenderAttrib.MLess))
        model.set_attrib(CullFaceAttrib.make(
            CullFaceAttrib.MCullCounterClockwise))
        model.set_attrib(ColorBlendAttrib.make(
            ColorBlendAttrib.MAdd, ColorBlendAttrib.OOne, ColorBlendAttrib.OOne))
        model.set_attrib(DepthWriteAttrib.make(DepthWriteAttrib.MOff))

        model.set_shader(loader.load_shader_GLSL(self.v.format(
            'sun_light'), self.f.format('sun_light'), self.shading_setup))
        p3d_light = deferred_render.attach_new_node(Spotlight("Spotlight"))
        #p3d_light.set_pos(render, pos)
        #p3d_light.set_hpr(render, hpr)
        p3d_light.look_at(-Vec3(*direction))
        p3d_light.set_y(p3d_light, -offset)
        #p3d_light.set_x(render, -offset)
        #p3d_light.node().set_exponent(20)
        if self.shadow_size > 0.0:
            p3d_light.node().set_shadow_caster(True, self.shadow_size, self.shadow_size)
            model.set_shader(loader.load_shader_GLSL(self.v.format(
            'sun_light'), self.f.format('sun_light_shadow'), self.shading_setup))
        #p3d_light.node().set_camera_mask(self.modelMask)
        try:
            model.set_shader_inputs(spot=p3d_light,bias= 0.0003, direction=Vec3(*direction))
        except AttributeError:
            model.set_shader_input('spot', p3d_light)
            model.set_shader_input('bias', 0.0003)
            model.set_shader_input('direction',Vec3(*direction))
        lens=OrthographicLens()
        lens.set_near_far(200.0, 1000.0)
        lens.set_film_size(1000, 1000)
        p3d_light.node().set_lens(lens)
        p3d_light.node().set_color(Vec4(color[0], color[1], color[2], 0.0))
        #p3d_light.node().showFrustum()
        return model, p3d_light

    def add_cone_light(self, color, pos=(0, 0, 0), hpr=(0, 0, 0),exponent=40,
                        radius=1.0, fov=45.0, shadow_size=0.0, bias=0.0005):
        """
        Creates a spotlight,
        use the ConeLight class, not this function!
        """
        if fov > 179.0:
            fov = 179.0
        xy_scale = math.tan(deg2Rad(fov * 0.5))
        model = loader.load_model("models/cone")
        # temp=model.copyTo(self.plain_root)
        # self.lights.append(model)
        model.reparent_to(self.light_root)
        model.set_scale(xy_scale, 1.0, xy_scale)
        model.flatten_strong()
        model.set_scale(radius)
        model.set_pos(pos)
        model.set_hpr(hpr)
        # debug=self.lights[-1].copyTo(self.plain_root)
        model.set_attrib(DepthTestAttrib.make(RenderAttrib.MLess))
        model.set_attrib(CullFaceAttrib.make(
            CullFaceAttrib.MCullCounterClockwise))
        model.set_attrib(ColorBlendAttrib.make(
            ColorBlendAttrib.MAdd, ColorBlendAttrib.OOne, ColorBlendAttrib.OOne))
        model.set_attrib(DepthWriteAttrib.make(DepthWriteAttrib.MOff))

        model.set_shader(loader.load_shader_GLSL(self.v.format(
            'spot_light'), self.f.format('spot_light'), self.shading_setup))
        model.set_shader_input("light_radius", float(radius))
        model.set_shader_input("light_pos", Vec4(pos, 1.0))
        model.set_shader_input("light_fov", deg2Rad(fov))
        p3d_light = render.attach_new_node(Spotlight("Spotlight"))
        p3d_light.set_pos(render, pos)
        p3d_light.set_hpr(render, hpr)
        p3d_light.node().set_exponent(exponent)
        p3d_light.node().set_color(Vec4(color, 1.0))
        if shadow_size > 0.0:
            p3d_light.node().set_shadow_caster(True, shadow_size, shadow_size)
            model.set_shader_input("bias", bias)
            model.set_shader(loader.load_shader_GLSL(self.v.format(
            'spot_light_shadow'), self.f.format('spot_light_shadow'), self.shading_setup))
        # p3d_light.node().set_camera_mask(self.modelMask)
        model.set_shader_input("spot", p3d_light)
        #p3d_light.node().showFrustum()
        p3d_light.node().get_lens().set_fov(fov)
        p3d_light.node().get_lens().set_far(radius)
        p3d_light.node().get_lens().set_near(1.0)
        #lens=OrthographicLens()
        #lens.set_near_far(5.0, 60.0)
        #lens.set_film_size(30, 30)
        #p3d_light.node().set_lens(lens)
        #p3d_light.node().showFrustum()
        return model, p3d_light

    def add_point_light(self, color, model="models/sphere", pos=(0, 0, 0), radius=1.0, shadow_size=0):
        """
        Creates a omni (point) light,
        Use the SphereLight class to create lights!!!
        """
        #print('make light, shadow', shadow_size)
        # light geometry
        # if we got a NodePath we use it as the geom for the light
        if not isinstance(model, NodePath):
            model = loader.load_model(model)
        # self.lights.append(model)
        model.set_shader(loader.load_shader_GLSL(self.v.format(
            'point_light'), self.f.format('point_light'), self.shading_setup))
        model.set_attrib(DepthTestAttrib.make(RenderAttrib.MLess))
        model.set_attrib(CullFaceAttrib.make(
            CullFaceAttrib.MCullCounterClockwise))
        model.set_attrib(ColorBlendAttrib.make(
            ColorBlendAttrib.MAdd, ColorBlendAttrib.OOne, ColorBlendAttrib.OOne))
        model.set_attrib(DepthWriteAttrib.make(DepthWriteAttrib.MOff))

        p3d_light = render.attach_new_node(PointLight("PointLight"))
        p3d_light.set_pos(render, pos)

        if shadow_size > 0:
            model.set_shader(loader.load_shader_GLSL(self.v.format(
                'point_light_shadow'), self.f.format('point_light_shadow'), self.shading_setup))
            p3d_light.node().set_shadow_caster(True, shadow_size, shadow_size)
            p3d_light.node().set_camera_mask(BitMask32.bit(13))
            for i in range(6):
                p3d_light.node().get_lens(i).set_near_far(0.1, radius)
                p3d_light.node().get_lens(i).make_bounds()

        # shader inputs
        try:
            model.set_shader_inputs(light= Vec4(color, radius * radius),
                                shadowcaster= p3d_light,
                                near= 0.1,
                                bias= (1.0/radius)*0.095)
        except AttributeError:
            model.set_shader_input('light', Vec4(color, radius * radius))
            model.set_shader_input('shadowcaster', p3d_light)
            model.set_shader_input('near',0.1)
            model.set_shader_input('bias', (1.0/radius)*0.095)

        model.reparent_to(self.light_root)
        model.set_pos(pos)
        model.set_scale(radius*1.1)

        return model, p3d_light

    def _make_FBO(self, name, auxrgba=0, multisample=0, srgb=False, depth_bits=32):
        """
        This routine creates an offscreen buffer.  All the complicated
        parameters are basically demanding capabilities from the offscreen
        buffer - we demand that it be able to render to texture on every
        bitplane, that it can support aux bitplanes, that it track
        the size of the host window, that it can render to texture
        cumulatively, and so forth.
        """
        winprops = WindowProperties()
        props = FrameBufferProperties()
        props.set_rgb_color(True)
        props.set_rgba_bits(8,8,8,8)
        props.set_depth_bits(depth_bits)
        props.set_aux_hrgba(auxrgba)
        #props.set_aux_rgba(auxrgba)
        props.set_srgb_color(srgb)
        if multisample>0:
            props.set_multisamples(multisample)
        return base.graphicsEngine.make_output(
            base.pipe, name, 2,
            props, winprops,
            GraphicsPipe.BFSizeTrackHost | GraphicsPipe.BFCanBindEvery |
            GraphicsPipe.BFRttCumulative | GraphicsPipe.BFRefuseWindow,
            base.win.get_gsg(), base.win)

    def _update(self, task):
        """
        Update task
        """
        self.plain_cam.set_pos_hpr(base.cam.get_pos(render), base.cam.get_hpr(render))

        for node, light, offset in self.attached_lights.values():
            if not node.is_empty():
                light.set_pos(render.get_relative_point(node, offset))
        return task.again

# this will replace the default Loader


# light classes:



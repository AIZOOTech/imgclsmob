"""
    Jasper for ASR, implemented in PyTorch.
    Original paper: 'Jasper: An End-to-End Convolutional Neural Acoustic Model,' https://arxiv.org/abs/1904.03288.
"""

__all__ = ['Jasper', 'jasper5x3', 'jasper10x4', 'jasper10x5', 'conv1d1', 'MaskConv1d', 'mask_conv1d1',
           'MaskConvBlock1d', 'mask_conv1d1_block', 'DwsConvBlock1d', 'JasperUnit', 'JasperFinalBlock']

import os
import torch
import torch.nn as nn
import torch.nn.functional as F
from .common import DualPathSequential, DualPathParallelConcurent


def conv1d1(in_channels,
            out_channels,
            stride=1,
            groups=1,
            bias=False):
    """
    1-dim kernel version of the 1D convolution layer.

    Parameters:
    ----------
    in_channels : int
        Number of input channels.
    out_channels : int
        Number of output channels.
    stride : int, default 1
        Strides of the convolution.
    groups : int, default 1
        Number of groups.
    bias : bool, default False
        Whether the layer uses a bias vector.
    """
    return nn.Conv1d(
        in_channels=in_channels,
        out_channels=out_channels,
        kernel_size=1,
        stride=stride,
        groups=groups,
        bias=bias)


class MaskConv1d(nn.Conv1d):
    """
    Masked 1D convolution block.

    Parameters:
    ----------
    in_channels : int
        Number of input channels.
    out_channels : int
        Number of output channels.
    kernel_size : int or tuple/list of 2 int
        Convolution window size.
    stride : int or tuple/list of 2 int
        Strides of the convolution.
    padding : int or tuple/list of 2 int, default 0
        Padding value for convolution layer.
    dilation : int or tuple/list of 2 int, default 1
        Dilation value for convolution layer.
    groups : int, default 1
        Number of groups.
    bias : bool, default False
        Whether the layer uses a bias vector.
    use_mask : bool, default True
        Whether to use mask.
    """
    def __init__(self,
                 in_channels,
                 out_channels,
                 kernel_size,
                 stride,
                 padding=0,
                 dilation=1,
                 groups=1,
                 bias=False,
                 use_mask=True):
        super(MaskConv1d, self).__init__(
            in_channels=in_channels,
            out_channels=out_channels,
            kernel_size=kernel_size,
            stride=stride,
            padding=padding,
            dilation=dilation,
            groups=groups,
            bias=bias)
        self.use_mask = use_mask

    def forward(self, x, x_len):
        if self.use_mask:
            x_len = x_len.to(dtype=torch.long)
            max_len = x.size(2)
            mask = torch.arange(max_len).to(x_len.device).expand(len(x_len), max_len) >= x_len.unsqueeze(1)
            x = x.masked_fill(mask=mask.unsqueeze(1).to(device=x.device), value=0)
            x_len = (x_len + 2 * self.padding[0] - self.dilation[0] * (self.kernel_size[0] - 1) -
                     1) // self.stride[0] + 1
        x = F.conv1d(
            input=x,
            weight=self.weight,
            bias=self.bias,
            stride=self.stride,
            padding=self.padding,
            dilation=self.dilation,
            groups=self.groups)
        return x, x_len


def mask_conv1d1(in_channels,
                 out_channels,
                 stride=1,
                 groups=1,
                 bias=False):
    """
    Masked 1-dim kernel version of the 1D convolution layer.

    Parameters:
    ----------
    in_channels : int
        Number of input channels.
    out_channels : int
        Number of output channels.
    stride : int, default 1
        Strides of the convolution.
    groups : int, default 1
        Number of groups.
    bias : bool, default False
        Whether the layer uses a bias vector.
    """
    return MaskConv1d(
        in_channels=in_channels,
        out_channels=out_channels,
        kernel_size=1,
        stride=stride,
        groups=groups,
        bias=bias)


class MaskConvBlock1d(nn.Module):
    """
    Masked 1D convolution block with batch normalization, activation, and dropout.

    Parameters:
    ----------
    in_channels : int
        Number of input channels.
    out_channels : int
        Number of output channels.
    kernel_size : int
        Convolution window size.
    stride : int
        Strides of the convolution.
    padding : int
        Padding value for convolution layer.
    dilation : int, default 1
        Dilation value for convolution layer.
    groups : int, default 1
        Number of groups.
    bias : bool, default False
        Whether the layer uses a bias vector.
    use_bn : bool, default True
        Whether to use BatchNorm layer.
    bn_eps : float, default 1e-5
        Small float added to variance in Batch norm.
    activation : function or str or None, default nn.ReLU(inplace=True)
        Activation function or name of activation function.
    dropout_rate : float, default 0.0
        Parameter of Dropout layer. Faction of the input units to drop.
    """
    def __init__(self,
                 in_channels,
                 out_channels,
                 kernel_size,
                 stride,
                 padding,
                 dilation=1,
                 groups=1,
                 bias=False,
                 use_bn=True,
                 bn_eps=1e-5,
                 activation=(lambda: nn.ReLU(inplace=True)),
                 dropout_rate=0.0):
        super(MaskConvBlock1d, self).__init__()
        self.activate = (activation is not None)
        self.use_bn = use_bn
        self.use_dropout = (dropout_rate != 0.0)

        self.conv = MaskConv1d(
            in_channels=in_channels,
            out_channels=out_channels,
            kernel_size=kernel_size,
            stride=stride,
            padding=padding,
            dilation=dilation,
            groups=groups,
            bias=bias)
        if self.use_bn:
            self.bn = nn.BatchNorm1d(
                num_features=out_channels,
                eps=bn_eps)
        if self.activate:
            self.activ = activation()
        if self.use_dropout:
            self.dropout = nn.Dropout(p=dropout_rate)

    def forward(self, x, x_len):
        x, x_len = self.conv(x, x_len)
        if self.use_bn:
            x = self.bn(x)
        if self.activate:
            x = self.activ(x)
        if self.use_dropout:
            x = self.dropout(x)
        return x, x_len


def mask_conv1d1_block(in_channels,
                       out_channels,
                       stride=1,
                       padding=0,
                       **kwargs):
    """
    1-dim kernel version of the masked 1D convolution block.

    Parameters:
    ----------
    in_channels : int
        Number of input channels.
    out_channels : int
        Number of output channels.
    stride : int, default 1
        Strides of the convolution.
    padding : int, default 0
        Padding value for convolution layer.
    """
    return MaskConvBlock1d(
        in_channels=in_channels,
        out_channels=out_channels,
        kernel_size=1,
        stride=stride,
        padding=padding,
        **kwargs)


class ChannelShuffle1d(nn.Module):
    """
    1D version of the channel shuffle layer.

    Parameters:
    ----------
    channels : int
        Number of channels.
    groups : int
        Number of groups.
    """
    def __init__(self,
                 channels,
                 groups):
        super(ChannelShuffle1d, self).__init__()
        if channels % groups != 0:
            raise ValueError("channels must be divisible by groups")
        self.groups = groups

    def forward(self, x):
        batch, channels, seq_len = x.size()
        channels_per_group = channels // self.groups
        x = x.view(batch, self.groups, channels_per_group, seq_len)
        x = torch.transpose(x, 1, 2).contiguous()
        x = x.view(batch, channels, seq_len)
        return x

    def __repr__(self):
        s = "{name}(groups={groups})"
        return s.format(
            name=self.__class__.__name__,
            groups=self.groups)


class DwsConvBlock1d(nn.Module):
    """
    Depthwise version of the 1D standard convolution block with batch normalization, activation, dropout, and channel
    shuffle.

    Parameters:
    ----------
    in_channels : int
        Number of input channels.
    out_channels : int
        Number of output channels.
    kernel_size : int
        Convolution window size.
    stride : int
        Strides of the convolution.
    padding : int
        Padding value for convolution layer.
    dilation : int, default 1
        Dilation value for convolution layer.
    groups : int, default 1
        Number of groups.
    bias : bool, default False
        Whether the layer uses a bias vector.
    use_bn : bool, default True
        Whether to use BatchNorm layer.
    bn_eps : float, default 1e-5
        Small float added to variance in Batch norm.
    activation : function or str or None, default nn.ReLU(inplace=True)
        Activation function or name of activation function.
    dropout_rate : float, default 0.0
        Parameter of Dropout layer. Faction of the input units to drop.
    """
    def __init__(self,
                 in_channels,
                 out_channels,
                 kernel_size,
                 stride,
                 padding,
                 dilation=1,
                 groups=1,
                 bias=False,
                 use_bn=True,
                 bn_eps=1e-5,
                 activation=(lambda: nn.ReLU(inplace=True)),
                 dropout_rate=0.0):
        super(DwsConvBlock1d, self).__init__()
        self.activate = (activation is not None)
        self.use_bn = use_bn
        self.use_dropout = (dropout_rate != 0.0)
        self.use_channel_shuffle = (groups > 1)

        self.dw_conv = MaskConv1d(
            in_channels=in_channels,
            out_channels=in_channels,
            kernel_size=kernel_size,
            stride=stride,
            padding=padding,
            dilation=dilation,
            groups=in_channels,
            bias=bias)
        self.pw_conv = mask_conv1d1(
            in_channels=in_channels,
            out_channels=out_channels,
            groups=groups,
            bias=bias)
        if self.use_channel_shuffle:
            self.shuffle = ChannelShuffle1d(
                channels=out_channels,
                groups=groups)
        if self.use_bn:
            self.bn = nn.BatchNorm1d(
                num_features=out_channels,
                eps=bn_eps)
        if self.activate:
            self.activ = activation()
        if self.use_dropout:
            self.dropout = nn.Dropout(p=dropout_rate)

    def forward(self, x, x_len):
        x, x_len = self.dw_conv(x, x_len)
        x, x_len = self.pw_conv(x, x_len)
        if self.use_channel_shuffle:
            x = self.shuffle(x)
        if self.use_bn:
            x = self.bn(x)
        if self.activate:
            x = self.activ(x)
        if self.use_dropout:
            x = self.dropout(x)
        return x, x_len


class JasperUnit(nn.Module):
    """
    Jasper unit with residual connection.

    Parameters:
    ----------
    in_channels : int or list of int
        Number of input channels.
    out_channels : int
        Number of output channels.
    kernel_size : int
        Convolution window size.
    bn_eps : float
        Small float added to variance in Batch norm.
    dropout_rate : float
        Parameter of Dropout layer. Faction of the input units to drop.
    repeat : int
        Count of body convolution blocks.
    use_dw : bool
        Whether to use depthwise block.
    use_dr : bool
        Whether to use dense residual scheme.
    """
    def __init__(self,
                 in_channels,
                 out_channels,
                 kernel_size,
                 bn_eps,
                 dropout_rate,
                 repeat,
                 use_dw,
                 use_dr):
        super(JasperUnit, self).__init__()
        self.use_dropout = (dropout_rate != 0.0)
        self.use_dr = use_dr
        block_class = DwsConvBlock1d if use_dw else MaskConvBlock1d

        if self.use_dr:
            self.identity_block = DualPathParallelConcurent()
            for i, dense_in_channels_i in enumerate(in_channels):
                self.identity_block.add_module("block{}".format(i + 1), mask_conv1d1_block(
                    in_channels=dense_in_channels_i,
                    out_channels=out_channels,
                    bn_eps=bn_eps,
                    dropout_rate=0.0,
                    activation=None))
            in_channels = in_channels[-1]
        else:
            self.identity_block = mask_conv1d1_block(
                in_channels=in_channels,
                out_channels=out_channels,
                bn_eps=bn_eps,
                dropout_rate=0.0,
                activation=None)

        self.body = DualPathSequential()
        for i in range(repeat):
            activation = (lambda: nn.ReLU(inplace=True)) if i < repeat - 1 else None
            dropout_rate_i = dropout_rate if i < repeat - 1 else 0.0
            self.body.add_module("block{}".format(i + 1), block_class(
                in_channels=in_channels,
                out_channels=out_channels,
                kernel_size=kernel_size,
                stride=1,
                padding=(kernel_size // 2),
                bn_eps=bn_eps,
                dropout_rate=dropout_rate_i,
                activation=activation))
            in_channels = out_channels

        self.activ = nn.ReLU(inplace=True)
        if self.use_dropout:
            self.dropout = nn.Dropout(p=dropout_rate)

    def forward(self, x, x_len):
        if self.use_dr:
            x_len, y, y_len = x_len if type(x_len) is tuple else (x_len, None, None)
            y = [x] if y is None else y + [x]
            y_len = [x_len] if y_len is None else y_len + [x_len]
            identity, _ = self.identity_block(y, y_len)
            identity = torch.stack(tuple(identity), dim=1)
            identity = identity.sum(dim=1)
        else:
            identity, _ = self.identity_block(x, x_len)

        x, x_len = self.body(x, x_len)
        x = x + identity
        x = self.activ(x)
        if self.use_dropout:
            x = self.dropout(x)

        if self.use_dr:
            return x, (x_len, y, y_len)
        else:
            return x, x_len


class JasperFinalBlock(nn.Module):
    """
    Jasper specific final block.

    Parameters:
    ----------
    in_channels : int
        Number of input channels.
    channels : list of int
        Number of output channels for each block.
    kernel_sizes : list of int
        Kernel sizes for each block.
    bn_eps : float
        Small float added to variance in Batch norm.
    dropout_rates : list of int
        Dropout rates for each block.
    use_dw : bool
        Whether to use depthwise block.
    use_dr : bool
        Whether to use dense residual scheme.
    """
    def __init__(self,
                 in_channels,
                 channels,
                 kernel_sizes,
                 bn_eps,
                 dropout_rates,
                 use_dw,
                 use_dr):
        super(JasperFinalBlock, self).__init__()
        self.use_dr = use_dr
        conv1_class = DwsConvBlock1d if use_dw else MaskConvBlock1d

        self.conv1 = conv1_class(
            in_channels=in_channels,
            out_channels=channels[-2],
            kernel_size=kernel_sizes[-2],
            stride=1,
            padding=(2 * kernel_sizes[-2] // 2 - 1),
            dilation=2,
            bn_eps=bn_eps,
            dropout_rate=dropout_rates[-2])
        self.conv2 = MaskConvBlock1d(
            in_channels=channels[-2],
            out_channels=channels[-1],
            kernel_size=kernel_sizes[-1],
            stride=1,
            padding=(kernel_sizes[-1] // 2),
            bn_eps=bn_eps,
            dropout_rate=dropout_rates[-1])

    def forward(self, x, x_len):
        if self.use_dr:
            x_len = x_len[0]
        x, x_len = self.conv1(x, x_len)
        x, x_len = self.conv2(x, x_len)
        return x, x_len


class Jasper(nn.Module):
    """
    Jasper model from 'Jasper: An End-to-End Convolutional Neural Acoustic Model,' https://arxiv.org/abs/1904.03288.

    Parameters:
    ----------
    channels : list of int
        Number of output channels for each unit and initial/final block.
    kernel_sizes : list of int
        Kernel sizes for each unit and initial/final block.
    bn_eps : float
        Small float added to variance in Batch norm.
    dropout_rates : list of int
        Dropout rates for each unit and initial/final block.
    repeat : int
        Count of body convolution blocks.
    use_dw : bool
        Whether to use depthwise block.
    use_dr : bool
        Whether to use dense residual scheme.
    in_channels : int, default 64
        Number of input channels (audio features).
    num_classes : int, default 29
        Number of classification classes (number of graphemes).
    """
    def __init__(self,
                 channels,
                 kernel_sizes,
                 bn_eps,
                 dropout_rates,
                 repeat,
                 use_dw,
                 use_dr,
                 in_channels=64,
                 num_classes=29):
        super(Jasper, self).__init__()
        self.in_size = None
        self.num_classes = num_classes

        self.features = DualPathSequential()
        init_block_class = DwsConvBlock1d if use_dw else MaskConvBlock1d
        self.features.add_module("init_block", init_block_class(
            in_channels=in_channels,
            out_channels=channels[0],
            kernel_size=kernel_sizes[0],
            stride=2,
            padding=(kernel_sizes[0] // 2),
            bn_eps=bn_eps,
            dropout_rate=dropout_rates[0]))
        in_channels = channels[0]
        in_channels_list = []
        for i, (out_channels, kernel_size, dropout_rate) in\
                enumerate(zip(channels[1:-2], kernel_sizes[1:-2], dropout_rates[1:-2])):
            in_channels_list += [in_channels]
            self.features.add_module("unit{}".format(i + 1), JasperUnit(
                in_channels=(in_channels_list if use_dr else in_channels),
                out_channels=out_channels,
                kernel_size=kernel_size,
                bn_eps=bn_eps,
                dropout_rate=dropout_rate,
                repeat=repeat,
                use_dw=use_dw,
                use_dr=use_dr))
            in_channels = out_channels
        self.features.add_module("final_block", JasperFinalBlock(
            in_channels=in_channels,
            channels=channels,
            kernel_sizes=kernel_sizes,
            bn_eps=bn_eps,
            dropout_rates=dropout_rates,
            use_dw=use_dw,
            use_dr=use_dr))
        in_channels = channels[-1]

        self.output = conv1d1(
            in_channels=in_channels,
            out_channels=num_classes,
            bias=True)

        self._init_params()

    def _init_params(self):
        for name, module in self.named_modules():
            if isinstance(module, nn.Conv2d):
                nn.init.kaiming_uniform_(module.weight)
                if module.bias is not None:
                    nn.init.constant_(module.bias, 0)

    def forward(self, x, x_len):
        x, x_len = self.features(x, x_len)
        x = self.output(x)
        return x, x_len


def get_jasper(version,
               bn_eps=1e-3,
               model_name=None,
               pretrained=False,
               root=os.path.join("~", ".torch", "models"),
               **kwargs):
    """
    Create Jasper model with specific parameters.

    Parameters:
    ----------
    version : str
        Model version.
    bn_eps : float, default 1e-3
        Small float added to variance in Batch norm.
    model_name : str or None, default None
        Model name for loading pretrained model.
    pretrained : bool, default False
        Whether to load the pretrained weights for model.
    root : str, default '~/.torch/models'
        Location for keeping the model parameters.
    """
    import numpy as np

    blocks, repeat = tuple(map(int, version.split("x")))
    main_stage_repeat = blocks // 5

    channels_per_stage = [256, 256, 384, 512, 640, 768, 896, 1024]
    kernel_sizes_per_stage = [11, 11, 13, 17, 21, 25, 29, 1]
    dropout_rates_per_stage = [0.2, 0.2, 0.2, 0.2, 0.3, 0.3, 0.4, 0.4]
    stage_repeat = np.full((8,), 1)
    stage_repeat[1:-2] *= main_stage_repeat
    channels = sum([[a] * r for (a, r) in zip(channels_per_stage, stage_repeat)], [])
    kernel_sizes = sum([[a] * r for (a, r) in zip(kernel_sizes_per_stage, stage_repeat)], [])
    dropout_rates = sum([[a] * r for (a, r) in zip(dropout_rates_per_stage, stage_repeat)], [])
    use_dw = False
    use_dr = False

    net = Jasper(
        channels=channels,
        kernel_sizes=kernel_sizes,
        bn_eps=bn_eps,
        dropout_rates=dropout_rates,
        repeat=repeat,
        use_dw=use_dw,
        use_dr=use_dr,
        **kwargs)

    if pretrained:
        if (model_name is None) or (not model_name):
            raise ValueError("Parameter `model_name` should be properly initialized for loading pretrained model.")
        from .model_store import download_model
        download_model(
            net=net,
            model_name=model_name,
            local_model_store_dir_path=root)

    return net


def jasper5x3(**kwargs):
    """
    Jasper 5x3 model from 'Jasper: An End-to-End Convolutional Neural Acoustic Model,'
    https://arxiv.org/abs/1904.03288.

    Parameters:
    ----------
    pretrained : bool, default False
        Whether to load the pretrained weights for model.
    root : str, default '~/.torch/models'
        Location for keeping the model parameters.
    """
    return get_jasper(version="5x3", model_name="jasper5x3", **kwargs)


def jasper10x4(**kwargs):
    """
    Jasper 10x4 model from 'Jasper: An End-to-End Convolutional Neural Acoustic Model,'
    https://arxiv.org/abs/1904.03288.

    Parameters:
    ----------
    pretrained : bool, default False
        Whether to load the pretrained weights for model.
    root : str, default '~/.torch/models'
        Location for keeping the model parameters.
    """
    return get_jasper(version="10x4", model_name="jasper10x4", **kwargs)


def jasper10x5(**kwargs):
    """
    Jasper 10x5 model from 'Jasper: An End-to-End Convolutional Neural Acoustic Model,'
    https://arxiv.org/abs/1904.03288.

    Parameters:
    ----------
    pretrained : bool, default False
        Whether to load the pretrained weights for model.
    root : str, default '~/.torch/models'
        Location for keeping the model parameters.
    """
    return get_jasper(version="10x5", model_name="jasper10x5", **kwargs)


def _calc_width(net):
    import numpy as np
    net_params = filter(lambda p: p.requires_grad, net.parameters())
    weight_count = 0
    for param in net_params:
        weight_count += np.prod(param.size())
    return weight_count


def _test():
    import numpy as np
    import torch

    pretrained = False
    audio_features = 64
    num_classes = 29

    models = [
        jasper5x3,
        jasper10x4,
        jasper10x5,
    ]

    for model in models:

        net = model(
            in_channels=audio_features,
            num_classes=num_classes,
            pretrained=pretrained)

        # net.train()
        net.eval()
        weight_count = _calc_width(net)
        print("m={}, {}".format(model.__name__, weight_count))
        assert (model != jasper5x3 or weight_count == 107681053)
        assert (model != jasper10x4 or weight_count == 261393693)
        assert (model != jasper10x5 or weight_count == 322286877)

        batch = 1
        seq_len = np.random.randint(60, 150)
        x = torch.randn(batch, audio_features, seq_len)
        x_len = torch.tensor(seq_len - 2, dtype=torch.long, device=x.device).unsqueeze(dim=0)
        y, y_len = net(x, x_len)
        # y.sum().backward()
        assert (tuple(y.size())[:2] == (batch, num_classes))
        assert (y.size()[2] in [seq_len // 2, seq_len // 2 + 1])


if __name__ == "__main__":
    _test()

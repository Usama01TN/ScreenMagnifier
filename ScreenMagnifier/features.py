# -*- coding: utf-8 -*-
"""
FeatureSettings: where the detection results are shown - the single source of truth shared by the Detection tab,
the Zoomer tab and the application logic (every checkbox bound to a feature follows changed()).
    zonesInMagnifier : color zones (and faces) drawn in the magnifier.
    zonesInZoomer    : color zones (and faces) drawn in the zoomer lens.
The zoomer's color code (live HEX under the crosshair) is a zoomer option (AdvancedOverlayController.setColorReadout).
"""
from ManyQt.QtCore import QObject, QSettings, pyqtSignal

FEATURES = {'zonesInMagnifier': True, 'zonesInZoomer': False}  # type: dict  # name -> default


class FeatureSettings(QObject):
    """
    FeatureSettings class.
    """
    changed = pyqtSignal('QString', bool)  # type: pyqtSignal

    def __init__(self, *args, **kwargs):
        """
        :param settings: (QSettings | None) None = ScreenMagnifier / Features.
        :param args: any
        :param kwargs: any
        """
        settings = kwargs.pop('settings', None)  # type: QSettings | None
        super(FeatureSettings, self).__init__(*args, **kwargs)
        self.__m_settings = settings if settings is not None else QSettings('ScreenMagnifier', 'Features')
        if self.__m_settings.value('zonesInZoomer', None) is None:  # Earlier versions: Detection tab option.
            old = QSettings('ScreenMagnifier', 'Detection').value('lens', None)
            if old is not None:
                self.__m_settings.setValue('zonesInZoomer', u'{}'.format(old).lower() in ('1', 'true', 'yes'))

    def get(self, name):
        """
        :param name: str | unicode | QString
        :return: bool
        """
        value = self.__m_settings.value(u'{}'.format(name), FEATURES.get(u'{}'.format(name), False))
        return u'{}'.format(value).lower() in ('1', 'true', 'yes')

    def set(self, name, on):
        """
        :param name: str | unicode | QString
        :param on: bool
        :return:
        """
        if self.get(name) != bool(on):
            self.__m_settings.setValue(u'{}'.format(name), bool(on))
            self.changed.emit(u'{}'.format(name), bool(on))
